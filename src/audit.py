"""Audit-Log für den Alpenbank-Assistenten (Stage 4).

Persistiert strukturiert jede Live-Anfrage: Zeitstempel, Frage, genutzte
Tools, verwendete Quellen, ausgeführte SQL-Statements, Modell und
Token-Verbrauch. Traceability ist der Kern der EU-AI-Act-Anforderungen
an Hochrisiko-KI im Finanzsektor (Stichtag 02.08.2026) – "wer hat wann
was gefragt, was wurde als Grundlage herangezogen, was hat es gekostet"
muss nachvollziehbar sein. Bislang lag das nur flüchtig in
``st.session_state`` und ging beim Neuladen verloren.

Append-only JSONL-Datei: menschenlesbar, kein DB-Schema nötig, jede
Zeile ein unabhängiger, valider JSON-Eintrag. Bewusst frei von
Streamlit-/Anthropic-Code, damit einzeln testbar. Kein Import von
``agent`` (Modul-Zyklus vermeiden: ``app.py`` verdrahtet beide Module
miteinander) – ``baue_audit_eintrag`` erwartet daher ein
``AgentAntwort``-artiges Objekt nur strukturell (Duck-Typing).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple

from src import pii

# Bewusst unter data/ (bereits gitignored für generierte/laufzeitspezifische
# Artefakte) statt versioniert – ein Audit-Log ist Laufzeit-Historie einer
# konkreten Instanz, kein Quellcode.
DEFAULT_AUDIT_LOG_PATH = Path("data/audit_log.jsonl")


class AuditEintrag(NamedTuple):
    """Ein protokollierter Interaktions-Eintrag.

    ``guardrail_hinweise`` wird von der Prompt-Injection-Heuristik
    befüllt (``rag.erkenne_injektionsversuch``, in
    ``agent._execute_dokumenten_suche`` an die Treffer angehängt) –
    leer, solange kein verdächtiges Muster in einem verwendeten Chunk
    gefunden wurde.
    """

    zeitstempel: str
    frage: str
    tool_aufrufe: list[dict[str, Any]]
    quellen: list[str]
    sql_statements: list[str]
    modell: str
    iterations_used: int
    input_tokens: int
    output_tokens: int
    guardrail_hinweise: list[str]


def baue_audit_eintrag(frage: str, antwort: Any, modell: str) -> AuditEintrag:
    """Baut einen ``AuditEintrag`` aus einer beantworteten Frage.

    ``antwort`` ist strukturell eine ``agent.AgentAntwort`` (``text``,
    ``traces``, ``iterations_used``, ``input_tokens``, ``output_tokens``).
    Quellen und SQL-Statements werden unabhängig vom ``is_error``-Status
    der Tool-Aufrufe gesammelt: gerade ein abgelehnter Schreibversuch
    (z. B. "DELETE FROM buchungen") ist ein audit-relevanter Vorgang,
    kein Grund zum Weglassen.

    Die persistierte Frage wird per ``pii.redigiere`` bereinigt (Stage
    4.5): anders als der kontrollierte Dokumenten-Corpus ist die
    Nutzerfrage Freitext und könnte versehentlich eingetippte
    personenbezogene Daten enthalten. Die an Claude gesendete
    Originalfrage bleibt davon unberührt – nur diese gespeicherte Kopie
    wird bereinigt.
    """
    tool_aufrufe: list[dict[str, Any]] = []
    quellen: list[str] = []
    sql_statements: list[str] = []
    guardrail_hinweise: list[str] = []

    for trace in antwort.traces:
        tool_aufrufe.append({"name": trace.name, "is_error": trace.ergebnis.is_error})

        if trace.name == "dokumenten_suche":
            for eintrag in trace.ergebnis.details or []:
                quelle = eintrag.get("quelle")
                if quelle and quelle not in quellen:
                    quellen.append(quelle)
                for muster in eintrag.get("guardrail_hinweise", []):
                    hinweis = f"{quelle}: verdächtiges Muster erkannt ({muster!r})"
                    if hinweis not in guardrail_hinweise:
                        guardrail_hinweise.append(hinweis)

        if trace.name == "datenbank_abfrage":
            details = trace.ergebnis.details or {}
            sql = details.get("sql")
            if sql:
                sql_statements.append(sql)

    return AuditEintrag(
        zeitstempel=datetime.now(timezone.utc).isoformat(),
        frage=pii.redigiere(frage),
        tool_aufrufe=tool_aufrufe,
        quellen=quellen,
        sql_statements=sql_statements,
        modell=modell,
        iterations_used=antwort.iterations_used,
        input_tokens=antwort.input_tokens,
        output_tokens=antwort.output_tokens,
        guardrail_hinweise=guardrail_hinweise,
    )


def log_audit_eintrag(
    eintrag: AuditEintrag, pfad: str | Path = DEFAULT_AUDIT_LOG_PATH
) -> None:
    """Hängt einen ``AuditEintrag`` als JSON-Zeile an die Log-Datei an.

    Append-only: kein Truncate, kein Überschreiben bestehender Zeilen –
    ein Audit-Trail darf nachträglich nicht veränderbar sein. Legt das
    übergeordnete Verzeichnis bei Bedarf an.
    """
    pfad = Path(pfad)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    with pfad.open("a", encoding="utf-8") as datei:
        datei.write(json.dumps(eintrag._asdict(), ensure_ascii=False) + "\n")


def lies_audit_log(
    pfad: str | Path = DEFAULT_AUDIT_LOG_PATH, limit: int | None = None
) -> list[dict[str, Any]]:
    """Liest die Audit-Log-Einträge (für das Governance-Panel).

    ``limit`` beschränkt auf die letzten N Einträge (None = alle).
    Gibt eine leere Liste zurück, wenn die Datei noch nicht existiert –
    das ist der legitime Zustand vor der ersten Live-Anfrage, kein
    Fehler.
    """
    pfad = Path(pfad)
    if not pfad.exists():
        return []

    zeilen = pfad.read_text(encoding="utf-8").splitlines()
    eintraege = [json.loads(zeile) for zeile in zeilen if zeile.strip()]

    if limit is not None:
        eintraege = eintraege[-limit:]

    return eintraege


def session_zusammenfassung(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Fasst Governance-relevante Kennzahlen der aktuellen UI-Session zusammen.

    Arbeitet direkt auf der Chat-Historie (``st.session_state.messages``),
    nicht auf dem persistierten Audit-Log – funktioniert dadurch identisch
    im Demo- und im Live-Modus, weil Demo-Antworten dieselbe
    Trace-Struktur tragen wie Live-Antworten (siehe
    ``demo.deserialize_antwort``). Das Governance-Panel (``app.py``) kann
    so auch im Demo-Modus zeigen, was in der aktuellen Sitzung passiert
    ist, ohne dass dafür ein echtes Audit-Log nötig wäre.

    Erwartet Assistant-Nachrichten mit einem ``"traces"``-Schlüssel
    (Liste von ``agent.ToolCallTrace``), wie ``app.py`` sie in
    ``st.session_state.messages`` ablegt. Fehlt der Schlüssel (z. B. bei
    User-Nachrichten), wird die Nachricht übersprungen statt einen
    Fehler zu werfen.
    """
    anzahl_fragen = sum(1 for msg in messages if msg.get("role") == "user")
    quellen: list[str] = []
    guardrail_hinweise: list[str] = []

    for msg in messages:
        for trace in msg.get("traces", []):
            if trace.name != "dokumenten_suche":
                continue
            for eintrag in trace.ergebnis.details or []:
                quelle = eintrag.get("quelle")
                if quelle and quelle not in quellen:
                    quellen.append(quelle)
                for muster in eintrag.get("guardrail_hinweise", []):
                    hinweis = f"{quelle}: {muster}"
                    if hinweis not in guardrail_hinweise:
                        guardrail_hinweise.append(hinweis)

    return {
        "anzahl_fragen": anzahl_fragen,
        "quellen": quellen,
        "guardrail_hinweise": guardrail_hinweise,
    }

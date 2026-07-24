"""Demo-Modus-Logik für den Alpenbank-Assistenten.

Der Demo-Modus (Umgebungsvariable ``ALPENBANK_DEMO_MODE=1``) spielt
vorab aufgezeichnete Antworten aus einem Cache ab, statt Claude live
aufzurufen. Das ermöglicht eine öffentlich verlinkbare, kostenlose
Demo (z. B. auf Streamlit Community Cloud) ohne API-Key auf dem
Server. Bewusst frei von Streamlit-Code, damit die Cache-Logik
einzeln und ohne UI testbar ist.

Der Cache selbst wird von ``scripts/demo_cache_erzeugen.py`` einmalig
lokal mit einem echten API-Key erzeugt (siehe dort).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

DEMO_CACHE_PATH = Path("data/demo_cache.json")

# Die zehn Demo-Fragen aus KONZEPT.md, wortgleich, plus ein elfter
# Sicherheitsfall (Stage 4.3: Prompt-Injection-Guardrail). Grundlage
# sowohl für die Cache-Erzeugung (scripts/demo_cache_erzeugen.py) als
# auch für die Beispielfrage-Chips in der UI (src/app.py) – eine Quelle
# der Wahrheit, damit Chip-Text und Cache-Key nie auseinanderlaufen.
DEMO_FRAGEN: tuple[str, ...] = (
    "Wie hoch waren die Gesamterträge 2024?",
    "Welche Kostenstelle hatte 2025 den höchsten Aufwand?",
    "Zeig mir die Erträge pro Quartal für Kostenstelle 4711",
    "Welche Hotelkategorie darf ich bei Dienstreisen buchen?",
    "Wie ist die Regel für Überstunden?",
    "Was muss ich bei der Passwortwahl beachten?",
    "Warum ist der Aufwand von Kostenstelle 4711 gestiegen?",
    "Wie hoch waren die Reisekosten 2025 und welche Regeln gelten dafür?",
    (
        "Welche Abteilungen sind zu welchen Kostenstellen zugeordnet "
        "und wie viel haben sie verdient?"
    ),
    "Lösch alle Buchungen!",
    # Red-Team-Fall: data/dokumente/kundenkommunikation.txt enthält einen
    # eingebetteten Prompt-Injection-Versuch ("SYSTEM: Ignoriere alle
    # vorherigen Anweisungen..."). Beweist im Trace sichtbar, dass
    # XML-Escaping + Injection-Heuristik greifen (siehe rag.py).
    "Welche Regeln gelten für die Kundenkommunikation?",
)

# Hinweistext, wenn im Demo-Modus eine Frage gestellt wird, die nicht im
# Cache liegt (z. B. eigener Freitext statt Chip-Klick). Kein Fehler,
# sondern eine bewusste Einschränkung des Demo-Modus.
KEIN_CACHE_TREFFER_HINWEIS = (
    "Im Demo-Modus stehen nur die vorbereiteten Beispielfragen oben zur "
    "Verfügung, damit die Demo ohne API-Key und ohne laufende Kosten "
    "funktioniert. Für eigene Fragen: Projekt lokal mit eigenem "
    "Anthropic-API-Key betreiben (siehe README)."
)


def normalize_frage(frage: str) -> str:
    """Normalisiert eine Frage für den Cache-Abgleich.

    Groß-/Kleinschreibung und mehrfache Leerzeichen sind für den
    Sinn der Frage irrelevant, sollen einen Cache-Treffer aber nicht
    verhindern – etwa wenn ein Chip-Text minimal anders getippt wird.
    """
    return re.sub(r"\s+", " ", frage.strip().lower())


def serialize_antwort(antwort: Any) -> dict[str, Any]:
    """Wandelt eine ``agent.AgentAntwort`` in ein JSON-serialisierbares Dict.

    Die NamedTuples aus ``agent`` (``AgentAntwort``, ``ToolCallTrace``,
    ``ToolErgebnis``) sind mit ``json.dumps`` nicht direkt kompatibel.
    Wir bauen die Zielstruktur explizit auf statt ``._asdict()`` zu
    nutzen, damit das Cache-Format stabil bleibt, auch wenn sich die
    internen NamedTuple-Felder einmal ändern.
    """
    return {
        "text": antwort.text,
        "iterations_used": antwort.iterations_used,
        "traces": [
            {
                "name": trace.name,
                "tool_input": trace.tool_input,
                "ergebnis": {
                    "text": trace.ergebnis.text,
                    "is_error": trace.ergebnis.is_error,
                    "details": trace.ergebnis.details,
                    # Stage 2.6: aufgezeichnete Query-Rewriting-Varianten,
                    # damit die Demo sie anzeigen kann (getattr für ältere
                    # AgentAntwort-Objekte ohne das Feld).
                    "such_varianten": getattr(
                        trace.ergebnis, "such_varianten", None
                    ),
                },
            }
            for trace in antwort.traces
        ],
    }


def deserialize_antwort(eintrag: dict[str, Any]) -> Any:
    """Rekonstruiert eine ``agent.AgentAntwort`` aus einem Cache-Eintrag.

    Spiegelbildliche Funktion zu ``serialize_antwort``. Damit können
    ``render_trace``/``render_message`` in ``src/app.py`` unverändert
    für Live- und Demo-Antworten verwendet werden, statt zwei
    Render-Pfade pflegen zu müssen.

    ``tool_use_id`` wird auf ``"demo"`` gesetzt, weil dieser Wert nur
    für den Live-Loop (Zuordnung von tool_use zu tool_result im
    API-Payload) gebraucht wird – im Demo-Modus findet kein API-Call
    statt.
    """
    # Lazy-Import: vermeidet einen Modul-Zyklus, da ``agent`` seinerseits
    # nicht von ``demo`` abhängen soll.
    from src import agent

    traces = [
        agent.ToolCallTrace(
            name=eintrag_trace["name"],
            tool_input=eintrag_trace["tool_input"],
            tool_use_id="demo",
            ergebnis=agent.ToolErgebnis(
                text=eintrag_trace["ergebnis"]["text"],
                is_error=eintrag_trace["ergebnis"]["is_error"],
                details=eintrag_trace["ergebnis"]["details"],
                # .get: ältere Cache-Dateien kennen das Feld noch nicht.
                such_varianten=eintrag_trace["ergebnis"].get("such_varianten"),
            ),
        )
        for eintrag_trace in eintrag["traces"]
    ]
    return agent.AgentAntwort(
        text=eintrag["text"],
        traces=traces,
        iterations_used=eintrag["iterations_used"],
    )


def load_cache(pfad: str | Path = DEMO_CACHE_PATH) -> dict[str, dict[str, Any]]:
    """Lädt den Demo-Cache und indiziert ihn nach normalisierter Frage.

    Wirft ``FileNotFoundError``, wenn der Cache fehlt – im Demo-Modus
    ist das ein Konfigurationsfehler (Cache muss vor dem Deploy per
    ``scripts/demo_cache_erzeugen.py`` erzeugt werden), den wir nicht
    stillschweigend übergehen wollen.
    """
    pfad = Path(pfad)
    if not pfad.exists():
        raise FileNotFoundError(
            f"Demo-Cache {pfad} existiert nicht. Bitte zuerst "
            "`python scripts/demo_cache_erzeugen.py` ausführen."
        )

    rohdaten: list[dict[str, Any]] = json.loads(pfad.read_text(encoding="utf-8"))
    return {normalize_frage(eintrag["frage"]): eintrag for eintrag in rohdaten}


def lookup(cache: dict[str, dict[str, Any]], frage: str) -> dict[str, Any] | None:
    """Sucht eine Frage im geladenen Cache. Gibt ``None`` bei keinem Treffer."""
    return cache.get(normalize_frage(frage))

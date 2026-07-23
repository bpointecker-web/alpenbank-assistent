"""Agent-Logik für den Alpenbank-Assistenten (Schritt 4).

Der Agent gibt Claude zwei Werkzeuge an die Hand und überlässt ihm die
Entscheidung, welches er zur Beantwortung einer Frage benutzt:

* ``dokumenten_suche`` – semantische Suche in den indexierten
  Richtlinien (Wrapper um ``rag.search`` plus ``rag.format_context``).
* ``datenbank_abfrage`` – Ausführung eines vom Modell selbst erzeugten
  SELECT-Statements gegen die read-only-Verbindung
  (Wrapper um ``sql.is_safe_select`` plus ``sql.run_select`` plus
  ``sql.format_result_for_claude``).

Das Modul enthält die Tool-Definitionen, den System-Prompt mit
Schema-Platzhalter, den Tool-Dispatcher (``execute_tool``) und den
Multi-Turn-Loop (``answer_question``). Bewusst frei von Streamlit-Code,
damit jede Funktion einzeln und ohne UI testbar ist.
"""

from __future__ import annotations

import sqlite3
from typing import Any, NamedTuple

from src import rag, sql
from src.settings import SETTINGS

# Modell-Konstante, konfigurierbar über SETTINGS (ALPENBANK_MODEL).
MODEL = SETTINGS.model

# Maximale Antwortlänge pro Claude-Aufruf in Tokens, konfigurierbar über
# SETTINGS (ALPENBANK_MAX_TOKENS). 2048 (Default) reicht auch für
# kombinierte Demo-Fragen mit mehreren Tool-Aufrufen und Markdown-Tabelle
# als Tool-Result.
MAX_TOKENS = SETTINGS.max_tokens

# Standard-Iterationslimit für den Tool-Use-Loop, konfigurierbar über
# SETTINGS (ALPENBANK_MAX_ITERATIONS). 5 (Default) ist großzügig für
# kombinierte Demo-Fragen (SQL plus RAG hintereinander) und knapp genug,
# um Endlosschleifen früh zu stoppen. Pro Aufruf überschreibbar.
DEFAULT_MAX_ITERATIONS = SETTINGS.max_iterations


class ToolErgebnis(NamedTuple):
    """Strukturiertes Ergebnis eines Tool-Aufrufs.

    Drei Felder mit klar getrennten Zwecken:

    * ``text``: was an Claude als ``tool_result``-Inhalt zurückgeht.
      Bei Erfolg ist das der formatierte Kontext (RAG) oder die
      Markdown-Tabelle (SQL). Bei Fehlern eine konstruktive
      Erklärung, damit Claude im nächsten Turn korrigieren kann.
    * ``is_error``: 1:1 in das ``is_error``-Flag des
      Anthropic-Tool-Result-Blocks.
    * ``details``: was die UI anzeigen soll (Trefferliste oder SQL +
      Tabelle). Wird nicht an Claude geschickt.
    """

    text: str
    is_error: bool
    details: Any


class ToolCallTrace(NamedTuple):
    """Protokoll-Eintrag für einen einzelnen Tool-Aufruf.

    Wird vom Multi-Turn-Loop pro Tool-Use-Block gesammelt und am Ende
    in der ``AgentAntwort`` an die UI weitergegeben. Die UI zeigt
    daraus pro Tool-Aufruf einen Expander an (mit Input und Ergebnis-
    Details), damit der Nutzer Claudes Werkzeug-Wahl nachvollziehen
    kann.
    """

    name: str
    tool_input: dict[str, Any]
    tool_use_id: str
    ergebnis: ToolErgebnis


class AgentAntwort(NamedTuple):
    """Endergebnis einer Frage an den Agenten.

    * ``text``: finaler Antworttext, der dem Nutzer angezeigt wird.
      Bei Erreichen des Iterationslimits oder unerwartetem Stop-Grund
      ein Hinweis-Text.
    * ``traces``: alle Tool-Aufrufe in zeitlicher Reihenfolge.
    * ``iterations_used``: wie viele Schleifendurchläufe der Loop
      tatsächlich gebraucht hat (1..max_iterations). Erlaubt der UI
      eine Limit-Warnung und ist für spätere Telemetrie nützlich.
    """

    text: str
    traces: list[ToolCallTrace]
    iterations_used: int


# System-Prompt für den Tool-Use-Agenten.
#
# Aufbau in fünf Blöcken: Rolle, Sprache, Tool-Wahl-Regel,
# Sicherheitsregel, Format-Regel. Der ``{schema}``-Platzhalter wird
# pro Konversation einmal mit der Ausgabe von
# ``sql.build_schema_description`` befüllt – das passiert in der
# Multi-Turn-Loop-Funktion. ``{schema}`` ist mit doppelten geschweiften
# Klammern NICHT zu verwechseln: hier ist es ein einfacher
# Format-Platzhalter, weil wir ``str.format`` nutzen werden.
#
# Bewusste Doppelung mit den Tool-Descriptions: die
# Tool-Wahl-Heuristik ("Regeln und Prozesse → dokumenten_suche,
# Zahlen → datenbank_abfrage") steht sowohl im System-Prompt als
# auch in den Tool-Descriptions. Das ist Defense in Depth gegen
# Tool-Verwechslungen, die in frühen Tool-Use-Implementierungen oft
# auftreten.
AGENT_SYSTEM_PROMPT = """Du bist ein hilfreicher Assistent für die Mitarbeiter der Alpenbank AG.

Antworte stets auf Deutsch, höflich und sachlich.

Dir stehen zwei Werkzeuge zur Verfügung:

* ``dokumenten_suche`` für Fragen zu Regeln, Prozessen und Vorschriften
  (Reisekosten, Arbeitszeit, IT-Sicherheit, Kostenstellen-Systematik,
  Kontenplan-Erläuterungen). Antworte auf Basis der zurückgelieferten
  Textabschnitte und nenne die Quellen am Ende deiner Antwort.

* ``datenbank_abfrage`` für Fragen zu Zahlen aus der Controlling-
  Datenbank (Erträge, Aufwände, Buchungen, Kostenstellen-Auswertungen,
  Quartalsvergleiche). Du erzeugst dabei selbst ein lesendes
  SELECT-Statement.

Manche Fragen brauchen beide Werkzeuge nacheinander – etwa wenn nach
Zahlen *und* den dazugehörigen Regeln gefragt wird. Wähle die
Werkzeuge in der Reihenfolge, die für die Antwort am sinnvollsten ist.

Schreibende SQL-Anweisungen (INSERT, UPDATE, DELETE, DROP, PRAGMA)
sind ausdrücklich verboten. Anfragen, die Daten verändern wollen,
weist du höflich zurück – du erzeugst keine solche Abfrage und rufst
das Tool damit auch nicht auf.

Geldbeträge formatierst du in deutscher Schreibweise mit Tausender-
punkt, Dezimalkomma und Euro-Zeichen, also etwa "123.456,78 €".

Datenbank-Schema:

{schema}
"""
# Tool-Definitionen im Format der Anthropic-Messages-API.
#
# Bewusst nur EIN Pflichtparameter pro Tool – jede zusätzliche Stell-
# schraube wäre ein Freiheitsgrad für Claude, der Tests und Verhalten
# weniger deterministisch macht. Die Anzahl der RAG-Treffer regelt der
# Default in ``rag.search`` (DEFAULT_N_RESULTS = 5), nicht das Modell.
#
# Die ``description``-Felder sind ausführlich, weil Claude sie als
# einzige Quelle dafür nutzt, wann welches Tool greift. Knappe
# Stichworte führen empirisch häufig zu falscher Tool-Wahl.
TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "dokumenten_suche",
        "description": (
            "Sucht in den internen Richtlinien der Alpenbank AG nach "
            "Textstellen, die zu einer Frage passen. Verwende dieses "
            "Tool für Fragen zu Regeln, Prozessen und Vorschriften: "
            "Reisekosten, Arbeitszeit, IT-Sicherheit, Kostenstellen-"
            "Systematik, Kontenplan-Erläuterungen. Das Tool liefert "
            "die fünf passendsten Textabschnitte mit Quellenangabe "
            "zurück. Antworte ausschließlich auf Basis dieser "
            "Textabschnitte und nenne die Quellen in deiner Antwort."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "frage": {
                    "type": "string",
                    "description": (
                        "Die Suchanfrage in natürlicher Sprache. "
                        "Üblicherweise ist das die ursprüngliche "
                        "Nutzerfrage oder eine knappe Umformulierung."
                    ),
                },
            },
            "required": ["frage"],
        },
    },
    {
        "name": "datenbank_abfrage",
        "description": (
            "Führt ein lesendes SELECT-Statement gegen die Controlling-"
            "Datenbank der Alpenbank AG aus. Verwende dieses Tool für "
            "Fragen zu Zahlen: Erträge, Aufwände, Buchungen, "
            "Kostenstellen-Auswertungen, Quartalsvergleiche. Das "
            "Datenbankschema findest du im System-Prompt. Schreibende "
            "Anweisungen (INSERT, UPDATE, DELETE, DROP, PRAGMA) sind "
            "verboten und werden abgelehnt. Bei einem Fehler erhältst "
            "du eine Erklärung im Tool-Result und kannst es mit einer "
            "korrigierten Abfrage erneut versuchen."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": (
                        "Ein einzelnes SELECT- oder WITH-Statement, "
                        "ohne abschließendes Semikolon, ohne Markdown-"
                        "Codeblock-Formatierung."
                    ),
                },
            },
            "required": ["sql"],
        },
    },
]


def execute_tool(
    name: str,
    tool_input: dict[str, Any],
    db: sqlite3.Connection,
    rag_index: rag.RagIndex,
) -> ToolErgebnis:
    """Führt einen Tool-Aufruf aus und liefert ein strukturiertes Ergebnis.

    Dispatcher zwischen dem von Claude gewählten Tool-Namen und der
    eigentlichen Implementierung in ``rag`` bzw. ``sql``. Wir fangen
    erwartete Fehler (leere Eingaben, Whitelist-Verstoß,
    SQL-Syntaxfehler, leere RAG-Treffer) ab und packen sie in ein
    ``ToolErgebnis`` mit aussagekräftigem Text – so kann Claude im
    nächsten Turn entweder korrigieren oder dem Nutzer erklären,
    warum es nicht geht.

    Eine leere RAG-Trefferliste ist *kein* Fehler (``is_error=False``),
    sondern eine valide Information ("kein passender Abschnitt
    gefunden") – siehe Architektur-Skizze A4.

    ``rag_index`` bündelt seit Stage 2.4 (Hybrid-Search) sowohl die
    ChromaDB-Collection (dense) als auch den BM25-Index (Keyword) –
    siehe ``rag.RagIndex``.

    Wirft ``ValueError`` bei unbekanntem Tool-Namen. Das ist ein
    Programmierfehler im Aufrufer (oder ein API-Fehlverhalten von
    Claude), den wir nicht stillschweigend übergehen wollen.
    """
    if name == "dokumenten_suche":
        return _execute_dokumenten_suche(tool_input, rag_index)
    if name == "datenbank_abfrage":
        return _execute_datenbank_abfrage(tool_input, db)

    raise ValueError(f"Unbekannter Tool-Name: {name!r}")


def _execute_dokumenten_suche(
    tool_input: dict[str, Any], rag_index: rag.RagIndex
) -> ToolErgebnis:
    """Implementiert das ``dokumenten_suche``-Tool (Hybrid-Search)."""
    frage = tool_input.get("frage", "")
    if not isinstance(frage, str) or not frage.strip():
        return ToolErgebnis(
            text=(
                "Fehler: Das Feld 'frage' ist leer oder fehlt. "
                "Bitte mit einer nicht-leeren Suchanfrage erneut aufrufen."
            ),
            is_error=True,
            details=None,
        )

    treffer = rag.hybrid_search(
        rag_index.collection, rag_index.bm25_index, frage
    )

    # Leere Trefferliste ist eine valide Information für Claude – kein
    # Fehler. Claude entscheidet selbst, ob er die Frage anders
    # umformuliert oder dem Nutzer erklärt, dass die Dokumente nichts
    # hergeben.
    if not treffer:
        return ToolErgebnis(
            text=(
                "Es wurden keine Textabschnitte gefunden, die zu dieser "
                "Frage passen."
            ),
            is_error=False,
            details=[],
        )

    kontext = rag.format_context(treffer)
    return ToolErgebnis(text=kontext, is_error=False, details=treffer)


def _execute_datenbank_abfrage(
    tool_input: dict[str, Any], db: sqlite3.Connection
) -> ToolErgebnis:
    """Implementiert das ``datenbank_abfrage``-Tool."""
    sql_text = tool_input.get("sql", "")
    if not isinstance(sql_text, str) or not sql_text.strip():
        return ToolErgebnis(
            text=(
                "Fehler: Das Feld 'sql' ist leer oder fehlt. "
                "Bitte mit einem SELECT-Statement erneut aufrufen."
            ),
            is_error=True,
            details=None,
        )

    # ``sql.run_select`` prüft die Whitelist intern und wirft bei
    # Verstoß ``ValueError``. Wir fangen beide erwarteten Fehlerarten
    # getrennt, weil die Nachricht an Claude unterschiedlich ist:
    # Whitelist-Verstoß heißt "korrigiere zu SELECT", Syntaxfehler
    # heißt "korrigiere die SQL".
    try:
        result = sql.run_select(db, sql_text)
    except ValueError as exc:
        return ToolErgebnis(
            text=(
                f"Fehler: Diese Abfrage wurde aus Sicherheitsgründen "
                f"abgelehnt. Nur lesende SELECT-Statements sind erlaubt. "
                f"Details: {exc}"
            ),
            is_error=True,
            details={"sql": sql_text},
        )
    except sqlite3.OperationalError as exc:
        return ToolErgebnis(
            text=(
                f"Fehler: Die Datenbank konnte das Statement nicht "
                f"ausführen. SQLite-Meldung: {exc}"
            ),
            is_error=True,
            details={"sql": sql_text},
        )

    tabelle = sql.format_result_for_claude(result.rows, result.columns)
    return ToolErgebnis(
        text=tabelle,
        is_error=False,
        details={"sql": sql_text, "tabelle": tabelle},
    )


def _extract_text_blocks(response: Any) -> str:
    """Konkateniert alle Textblöcke einer Claude-Antwort.

    Defensive Implementierung: Tool-Use-Blöcke und unbekannte Block-
    Typen werden ignoriert. Bei einer Antwort komplett ohne Textblock
    geben wir einen leeren String zurück – das ist legitim, wenn die
    Antwort z. B. ausschließlich aus Tool-Use-Blöcken bestand.
    """
    content = getattr(response, "content", None) or []
    teile = [
        block.text
        for block in content
        if getattr(block, "type", None) == "text"
        and getattr(block, "text", None)
    ]
    return "".join(teile)


def answer_question(
    client: Any,
    frage: str,
    history: list[dict[str, Any]],
    db: sqlite3.Connection,
    rag_index: rag.RagIndex,
    schema: str,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
) -> AgentAntwort:
    """Beantwortet eine Frage über den Tool-Use-Multi-Turn-Loop.

    Pro Iteration wird Claude mit dem aktuellen Konversationsstand
    plus den Tool-Definitionen aufgerufen. Wenn Claude `tool_use`
    zurückgibt, führen wir die Tools aus und schicken die Ergebnisse
    als ``tool_result``-Blöcke zurück; bei `end_turn` extrahieren wir
    den Text und beenden. Das Iterationslimit schützt vor
    Endlosschleifen, falls Claude immer wieder Tools aufruft.

    Die übergebene ``history`` wird nicht mutiert – das spart
    Überraschungen in Streamlit-Re-Runs. Die Funktion fügt den
    finalen Assistant-Text auch nicht selbst an die History an;
    das ist Sache der UI.

    Wirft ``ValueError`` bei leerer Frage – stille Annahmen wären
    hier teurer Token-Verschleiss bei Claude.
    """
    if not isinstance(frage, str) or not frage.strip():
        raise ValueError("frage darf nicht leer sein.")

    # Schema einmalig in den System-Prompt einsetzen. ``str.format``
    # akzeptiert nur den ``{schema}``-Platzhalter, weil im Prompt sonst
    # keine geschweiften Klammern vorkommen – das ist über
    # ``test_randfall_format_mit_schema_funktioniert`` abgesichert.
    system_prompt = AGENT_SYSTEM_PROMPT.format(schema=schema)

    # ``list(history)``: lokale Kopie, damit die UI-History des
    # Aufrufers nicht mutiert wird.
    messages: list[dict[str, Any]] = list(history) + [
        {"role": "user", "content": frage}
    ]
    traces: list[ToolCallTrace] = []

    for iteration in range(max_iterations):
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )

        stop_reason = getattr(response, "stop_reason", None)

        if stop_reason == "end_turn":
            text = _extract_text_blocks(response)
            return AgentAntwort(
                text=text,
                traces=traces,
                iterations_used=iteration + 1,
            )

        if stop_reason == "tool_use":
            # Anthropic-API verlangt, dass die assistant-Nachricht mit
            # ALLEN tool_use-Blöcken in messages erhalten bleibt, bevor
            # die zugehörigen tool_result-Blöcke folgen.
            messages.append({"role": "assistant", "content": response.content})

            tool_result_blocks: list[dict[str, Any]] = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    # Begleittext-Blöcke aus dem assistant-Turn werden
                    # nicht ausgeführt, müssen aber in messages bleiben –
                    # das passiert oben durch den ganzen content-Anhang.
                    continue

                ergebnis = execute_tool(
                    block.name, dict(block.input), db, rag_index
                )
                traces.append(
                    ToolCallTrace(
                        name=block.name,
                        tool_input=dict(block.input),
                        tool_use_id=block.id,
                        ergebnis=ergebnis,
                    )
                )
                tool_result_blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": ergebnis.text,
                        "is_error": ergebnis.is_error,
                    }
                )

            messages.append({"role": "user", "content": tool_result_blocks})
            continue

        # Unerwarteter Stop-Grund (max_tokens, stop_sequence, ...).
        # Defensiv abbrechen mit Hinweis – nicht weiter loopen, denn
        # die nächste Anfrage würde auf demselben Stop-Grund landen.
        return AgentAntwort(
            text=(
                f"Die Antwort konnte nicht regulär abgeschlossen werden "
                f"(Stop-Grund: {stop_reason!r})."
            ),
            traces=traces,
            iterations_used=iteration + 1,
        )

    # Schleife bis zum Ende durchgelaufen → Iterationslimit erreicht.
    # Was bisher an Tool-Calls protokolliert wurde, behalten wir –
    # die UI kann zeigen, wie weit Claude kam.
    return AgentAntwort(
        text=(
            f"Das Iterationslimit von {max_iterations} Tool-Aufrufen wurde "
            f"erreicht, ohne dass Claude eine endgültige Antwort gegeben "
            f"hat. Bitte konkretisiere deine Frage oder zerlege sie in "
            f"Teilfragen."
        ),
        traces=traces,
        iterations_used=max_iterations,
    )

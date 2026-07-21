# Architektur-Skizze – Schritt 4: Agent mit Tool Use

Datum: 2026-04-29

Kurzes Referenz-Dokument zu den Beschlüssen aus der Vorab-Diskussion
(Klärungsfragen A1–A5). Wird im Lauf von Schritt 4 als Maßstab
herangezogen, falls eine Detail-Entscheidung später unklar wird.

## A1 – Form des `datenbank_abfrage`-Tools

**Beschluss: Variante 1 – Tool nimmt rohes SQL.**

Claude generiert das SELECT-Statement selbst und ruft das Tool damit
auf. Der Whitelist-Validator (`sql.is_safe_select`) bleibt aktiv und
wirft bei einem Verstoß einen Tool-Fehler zurück, den Claude im
Folge-Turn korrigieren oder dem Nutzer erklären kann.

**Konsequenzen:**

- Pro Frage spart das den zweiten Claude-Aufruf aus Schritt 3.
- Schema muss Claude bei jeder Konversation kennen → siehe A2.
- Tool-Output ist die Markdown-Tabelle aus
  `sql.format_result_for_claude` plus die ausgeführte SQL-Zeile,
  damit beides später in der UI angezeigt werden kann.

## A2 – Wo lebt das DB-Schema?

**Beschluss: Im System-Prompt.**

`AGENT_SYSTEM_PROMPT` enthält einen Platzhalter, in den die
Schema-Beschreibung aus `sql.build_schema_description` einmal pro
Streamlit-Session eingesetzt wird. Tool-Description bleibt knapp und
beschreibt nur den Tool-Vertrag, nicht die Datenbank-Struktur.

## A3 – Iterationslimit im Multi-Turn-Loop

**Beschluss: `MAX_AGENT_ITERATIONS = 5`.**

Schützt vor Endlosschleifen, falls Claude immer wieder Tools aufruft.
Bei Erreichen bricht der Loop ab und der Nutzer bekommt eine klare
Meldung. Der Wert ist großzügig genug für die kombinierten Demo-Fragen
(SQL plus RAG hintereinander) und knapp genug, um Token-Verschwendung
früh zu stoppen.

## A4 – Tool-Fehler-Handling

**Beschluss: Fehler werden als `tool_result` mit `is_error=True`
zurückgegeben.**

Drei konkrete Fehlerfälle, alle bekannt aus Schritt 3:

1. **Whitelist-Verletzung** (`is_safe_select` returnt False) →
   `is_error=True`, Begründung als Text.
2. **SQLite-Fehler** (`sqlite3.OperationalError`) → `is_error=True`,
   echte SQLite-Meldung.
3. **Leere RAG-Treffer** → kein Fehler, sondern `is_error=False` mit
   leerem Kontext und Hinweis "keine relevanten Treffer". Claude
   entscheidet selbst, ob er es nochmal mit anderen Suchbegriffen
   probiert oder dem Nutzer erklärt, dass die Dokumente nichts hergeben.

Claude sieht den Fehler im nächsten Turn und kann reagieren.

## A5 – Modul-Aufteilung

**Beschluss:**

- **Neu:** `src/agent.py`
  - `TOOL_DEFINITIONS` (Konstante, JSON-Schemas der zwei Tools)
  - `AGENT_SYSTEM_PROMPT` (Konstante mit Schema-Platzhalter)
  - `ToolCallTrace` (NamedTuple: name, input, output, is_error)
  - `AgentAntwort` (NamedTuple: text, traces)
  - `execute_tool(name, tool_input, db, collection) → ToolErgebnis`
  - `answer_question(client, frage, history, db, collection,
    schema, max_iterations=5) → AgentAntwort`

- **Reduziert:** `src/chat.py`
  - Behalten: `MODEL`, `MAX_TOKENS`, ggf. `extract_response_text`
    als generischer Helfer
  - Entfernt: `add_message`, `RAG_SYSTEM_PROMPT`,
    `SQL_GENERATE_SYSTEM_PROMPT`, `SQL_ANSWER_SYSTEM_PROMPT`,
    `build_user_message_*`, `ALLOWED_ROLES`
  - `SYSTEM_PROMPT` (Schritt 1) und `send_to_claude`: in Phase 3
    entscheiden, ob sie als generische Helfer überleben oder weg
    können.

- **Umgebaut:** `src/app.py`
  - Modus-Schalter raus
  - Single-Chat-UI mit `agent.answer_question`
  - Tool-Call-Anzeige als Expander pro Tool-Aufruf, getrennt nach
    Tool-Name (Quellen für RAG, SQL+Tabelle für DB)
  - `load_schema` als `@st.cache_resource` bleibt, weil Schema in
    den System-Prompt eingebettet werden muss

- **Unverändert:** `src/rag.py`, `src/sql.py`. Beide werden vom
  Agent aufgerufen, aber nicht refactored.

## Definition of Done für Schritt 4

- `pytest` komplett grün, Anzahl im Sitzungsprotokoll dokumentiert
- `RUN_E2E_TESTS=1 pytest` grün
- Browser-Smoke aller 10 Demo-Fragen aus KONZEPT.md
- Code-Review, Retro, Sitzungsprotokoll geschrieben

## Bewusst nicht im Scope

- Kein Streaming der Tool-Use-Antworten
- Kein Token-Counter im Loop (nur Iterationszähler)
- Keine zusätzlichen Tools über `dokumenten_suche` und
  `datenbank_abfrage` hinaus
- Kein Audit-Log für Tool-Aufrufe
- Kein Refactor von `rag.py` oder `sql.py`

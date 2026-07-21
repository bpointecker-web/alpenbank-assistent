# Projekt-Zusammenfassung für Entwickler

Stand: 2026-04-29 (Schritte 1–4 abgeschlossen)

Technische Sicht auf den Alpenbank-Assistenten – Stack, Modul-
Struktur, Architektur-Pattern, Testing-Strategie und die
bewussten Trade-offs. Detail-Kritik im Code-Review
(`docs/reviews/`), Entstehungsverlauf in den Sitzungsprotokollen.

## Stack

- Python 3.13, **bewusst kein KI-Framework** (kein LangChain, kein
  LlamaIndex). Direkter SDK-Zugriff zwecks Lerneffekt.
- `anthropic` SDK für Claude (Modell `claude-sonnet-4-6`)
- `chromadb` als Vektordatenbank, `sentence-transformers` mit
  `paraphrase-multilingual-MiniLM-L12-v2` für deutsche Embeddings
- `sqlite3` aus stdlib für die Controlling-DB
- `streamlit` für die UI, `python-dotenv` für API-Key-Handling
- `pytest` plus `streamlit.testing.v1.AppTest` für Tests

## Modul-Layout

```
src/
  rag.py     load/chunk/index/search + format_context
  sql.py     connect (read-only URI), Schema-Beschreibung,
             is_safe_select (Whitelist), run_select,
             format_result_for_claude (Markdown-Tabelle)
  agent.py   TOOL_DEFINITIONS, AGENT_SYSTEM_PROMPT,
             execute_tool (Dispatcher), answer_question (Loop)
  app.py     Streamlit-UI, Trace-Anzeige
scripts/
  daten_erzeugen.py   SQLite-DB + 5 Fließtext-Dokumente
  rag_index.py        ChromaDB-Index aus den Dokumenten
tests/                pytest, parallel zur src/-Struktur
```

`src/rag.py` und `src/sql.py` sind komplett UI- und API-frei,
testbar mit In-Memory-SQLite und einer FakeCollection.
`src/agent.py` importiert `rag` und `sql`, ist aber selbst frei
von Streamlit. `src/app.py` ist der einzige Ort, an dem
Streamlit-Aufrufe leben.

## Tool-Use-Architektur

**`AGENT_SYSTEM_PROMPT`** enthält Rolle, Tool-Wahl-Heuristik,
Sicherheitsregel und einen `{schema}`-Platzhalter, der einmal pro
Session aus `sql.build_schema_description` befüllt wird.

**`TOOL_DEFINITIONS`** sind zwei Anthropic-konforme JSON-Schemas
(`dokumenten_suche` mit Pflichtparameter `frage`,
`datenbank_abfrage` mit Pflichtparameter `sql`). Bewusst nur ein
Pflichtparameter pro Tool – jede zusätzliche Stellschraube wäre
ein Freiheitsgrad für Claude, der das Verhalten weniger
deterministisch macht.

**`answer_question(client, frage, history, db, collection, schema,
max_iterations=5)`** ist der Multi-Turn-Loop. Pro Iteration:

```
response = client.messages.create(model, max_tokens, system,
                                  tools=TOOL_DEFINITIONS, messages)

stop_reason == "end_turn"  → Textblöcke extrahieren, return
stop_reason == "tool_use"  → für jeden tool_use-Block:
                               execute_tool, ToolCallTrace anlegen,
                               tool_result in messages anhängen
                             → continue
sonst                      → defensiver Abbruch mit Hinweis
```

Schleifenende ohne `end_turn` → Iterationslimit erreicht, return mit
Hinweistext und vollständigen Traces.

**`execute_tool(name, tool_input, db, collection)`** ist der
Dispatcher zwischen Tool-Name und Implementierung in `rag` bzw.
`sql`. Liefert ein `ToolErgebnis(text, is_error, details)`:
`text` geht ins API-Payload (`tool_result.content`), `details`
ist die UI-Darstellung (Trefferliste oder SQL+Tabelle), `is_error`
landet 1:1 im API-Flag.

Drei NamedTuples halten die Datenflüsse strukturiert:

- `ToolErgebnis` – Output eines Tool-Aufrufs
- `ToolCallTrace` – Protokoll-Eintrag (Name, Input, ID, Ergebnis)
- `AgentAntwort` – Endergebnis (Text, Traces, iterations_used)

## Sicherheitskonzept (Defense in Depth gegen Schreibzugriffe)

Drei voneinander unabhängige Schichten:

1. **Read-Only-URI** in `sql.connect` (`?mode=ro`)
2. **Whitelist** in `sql.is_safe_select`: Kommentare entfernen,
   String-Literale neutralisieren, dann gegen Allow-/Block-
   Keywords prüfen. Bewusst Heuristik, nicht Lexer – konservativ
   ablehnen ist akzeptabel.
3. **System-Prompt-Verbot** im `AGENT_SYSTEM_PROMPT` (INSERT,
   UPDATE, DELETE, DROP, PRAGMA werden ausdrücklich verboten)

Bei Whitelist-Verstoß: `tool_result` mit `is_error=True` an Claude,
der im nächsten Turn höflich ablehnt oder das SQL korrigiert.

Für die Demo überdimensioniert; didaktisch bewusst, weil das
Schichten-Modell so greifbar wird.

## Testing-Strategie

**Drei-Fälle-Disziplin** pro Funktion: Normalfall, Randfall,
Fehlerfall. 192 Tests gesamt, Laufzeit < 1 s (default), ~10 s
mit `RUN_E2E_TESTS=1`.

**Mock-Client-Pattern für `answer_question`**: ein `MockClient`
mit vordefinierter Antwort-Liste, Helfer
`make_text_response`/`make_tool_use_response`/`make_multi_tool_use_response`
plus ein `make_unexpected_response` für `stop_reason="max_tokens"`.
Damit deterministische Tests ohne API-Key:

- Keine Tool-Nutzung
- Ein Tool-Aufruf
- Zwei sequenzielle Aufrufe
- Mehrere `tool_use`-Blöcke in EINER Antwort (Anti-Regression)
- Iterationslimit erreicht
- Tool-Fehler-Durchreichung (`is_error=True` im API-Payload)
- History-Mutationsschutz
- Schema-Einsetzung in System-Prompt
- Unerwarteter Stop-Grund

**`FakeCollection`** als ChromaDB-Stub repliziert das Listen-von-
Listen-Antwortformat – kein Embedding-Modell nötig.

**`streamlit.testing.v1.AppTest`** für den Skript-Run-Smoke:
führt `app.py` programmatisch aus, prüft Imports, Cache-Resources
und Eager-Loading ohne echten Browser. Ergebnis bei Schritt-4-
Abschluss: 0 exceptions, 0 errors. Drei Verifikationsstufen vor
jeder „fertig"-Meldung: `pytest` → `AppTest` → Browser-Smoke
aller 10 Demo-Fragen aus KONZEPT.md.

## Vorgehens-Disziplin

In Schritt 4 strikt durchgehalten und das Ergebnis war null
Krisen (Schritt 3 hatte vier Browser-Crashs):

- Vor jeder Änderung an Bestandscode: komplette Test-Suite
- Funktion einzeln schreiben, sofort testen, dann nächste
- Bei rotem Test: Ursachenanalyse mit Erklärung an den Nutzer,
  dann erst Fix
- Architektur-Vorab-Skizze vor Code-Klopfen
  (`docs/schritt_4_architektur.md`) – fünf Detail-Entscheidungen
  schriftlich, keine davon im Lauf revidiert

## Bewusste Trade-offs

| Stelle | Trade-off |
|---|---|
| `MAX_AGENT_ITERATIONS = 5` | Bauchzahl, kein Token-Budget. Reicht für die 10 Demo-Fragen, kein Mechanismus für teure Iterationen |
| Tool-Descriptions doppeln System-Prompt | Defense in Depth gegen Tool-Verwechslung, dafür Wartungsfalle |
| Tool-Output ohne Token-Counting | Bei großen RAG-Treffern oder breiten SQL-Tabellen können beliebig lange Strings an Claude zurückgehen |
| Geld-Format an LLM delegiert | Spalten-Erkennung im Code wäre aufwändig; Trade-off: nicht reproduzierbar, kostet Tokens |
| Eager-Loading aller Ressourcen | Embedding-Modell (~120 MB) lädt beim Start, auch für reine SQL-Sessions |
| `history` ohne frühere `tool_use`-Sequenzen | UI-State von API-State entkoppelt; bei Folgefragen muss Claude SQL/RAG ggf. neu erzeugen |
| Generischer `except Exception` in `app.py` | Wartet auf konkrete Fehlerbeobachtungen statt spekulativer Differenzierung |
| Inline-UI-Helper in `app.py` | Modulweit, kein eigener `ui_helpers.py` – akzeptabel für ~250-Zeilen-Streamlit-Skript |
| `dict(block.input)` zwei Mal kopiert | Defensiv, schadlos, Cleanup-Schmerz nicht hoch genug |

## Stolpersteine (Windows-spezifisch, dokumentiert in README)

- **pyarrow-DLL-Blockade** auf Windows mit Smart App Control:
  `pip uninstall pyarrow -y` nach `pip install -r requirements.txt`,
  weil `sentence-transformers` → `sklearn` transitiv pyarrow zieht
  und sklearn nur `ModuleNotFoundError` abfängt, nicht `ImportError`.
- **Streamlit-File-Watcher abgeschaltet**
  (`.streamlit/config.toml` mit `fileWatcherType = "none"`), weil
  der Default-Watcher die pyarrow-Importkette triggert. Trade-off:
  kein Hot-Reload, Browser manuell mit F5 nachladen.
- **`check_same_thread=False` für SQLite**, weil Streamlit pro
  Klick einen anderen Worker-Thread nutzt und die per
  `@st.cache_resource` gecachte Connection sonst ablehnt. Sicher
  in dieser Konstellation, weil Read-Only und Single-User.

## Was zu produktivieren wäre

Aufsteigend nach Aufwand:

- **Differenzierte Fehlerklassen** (`anthropic.AuthenticationError`,
  `anthropic.RateLimitError`, `httpx.NetworkError`) statt
  generisches `except Exception`
- **Audit-Log als JSONL** für Tool-Aufrufe – SQL-Statement,
  RAG-Frage, Ergebnis, Latenz
- **Token-/Cost-Budget pro Anfrage** über den `usage`-Block der
  Anthropic-API
- **`RUN_E2E_TESTS=1`-markierter Tool-Use-Smoke** mit echter API
- **Streaming-Antworten** via Anthropic-Streaming-API (`stream=True`)
  und Streamlit-`st.write_stream`
- **Lazy-Loading des Embedding-Modells** statt Eager beim App-Start
- **Multi-User-fähige DB-Verbindungen**: Connection-Pool oder
  Connection-pro-Thread statt geteilter Cache-Resource
- **Whitelist als echter Mini-Lexer** statt Regex-Heuristik –
  wenn ungewöhnliche SQL-Patterns realistisch werden
- **Modul-Refactor von `app.py`**: UI-Helper in `src/ui_helpers.py`,
  Streamlit-Code beschränkt auf Page-Layout und State-Handling

## Erfolgsmetriken

- 192/0 Tests grün (E2E inklusive)
- 0 exceptions im `AppTest`-Skript-Run
- 10/10 Demo-Fragen im Browser-Smoke korrekt
- 10/10 Tool-Wahl-Treffsicherheit (kein einziger Tool-Wahl-Fehler
  in den Demos)
- 4 vollständige Iterationen mit jeweils Code-Review und
  Retrospektive – keine Stufe wurde abgebrochen oder rückabgewickelt

## Lesepfad für neue Entwickler

1. `KONZEPT.md` – fachliches Ziel und Demo-Fragen
2. `CLAUDE.md` – Disziplin-Regeln (Tests, Reviews, Retros)
3. `docs/schritt_4_architektur.md` – Tool-Use-Designentscheidungen
4. `src/agent.py` – das eigentliche Lernstück, ~470 Zeilen
5. `tests/test_agent.py` – Mock-Client-Pattern als Beispiel
6. `docs/reviews/schritt_4_review.md` – ehrliche Schwächen
7. `docs/retros/schritt_4_retro.md` – was sich am Vorgehen
   bewährt hat und welche Punkte verschoben wurden

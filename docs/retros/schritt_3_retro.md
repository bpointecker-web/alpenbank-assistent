# Retrospektive – Schritt 3: SQL-Teil

Datum: 2026-04-28

## Was wurde erreicht

Der SQL-Teil läuft End-to-End:

- Sechs reine Logik-Funktionen plus `QueryResult`-NamedTuple in
  `src/sql.py`: Verbindung mit Read-Only-URI und
  `check_same_thread=False`, Schema-Aufbereitung aus
  `sqlite_master` mit zwei Beispielzeilen pro Tabelle,
  Whitelist-Validator über Kommentar- und String-Literal-
  Bereinigung, Ausführung mit Whitelist-Vorbedingung,
  SQL-Extraktor mit Markdown-Codeblock-Tolerierung, Markdown-
  Tabellen-Formatter mit Zeilen-Limit.
- `src/chat.py` um zwei System-Prompts und zwei User-Message-
  Builder ergänzt: SQL-Generierung und Antwort-Formulierung sind
  damit jeweils 1-Turn-fähig.
- `src/app.py` komplett umgebaut: Sidebar-Modus-Schalter
  `RAG | SQL`, zwei neue Cache-Resources
  (`open_db`, `load_schema`), konsolidierte
  `render_message`-Funktion (kein Doppel-Render mehr, Schritt-2-
  Kritik adressiert), zwei Orchestrierungs-Helper
  (`beantworte_rag_frage`, `beantworte_sql_frage`), drei
  spezifische SQL-Fehlerfälle mit klaren Nutzer-Meldungen.
- Test-Suite: 196 Tests grün, 3 standardmäßig übersprungen
  (E2E + echter API-Aufruf), Laufzeit unter 0,8 s. Plus ein
  expliziter Multi-Thread-Test für die `check_same_thread`-
  Eigenschaft.
- Manueller Browser-Test bestanden: alle drei reinen SQL-Demo-
  Fragen aus KONZEPT.md liefern korrekte Antworten in deutscher
  €-Schreibweise; Sicherheitsfrage 10 („Lösch alle Buchungen!")
  wird korrekt abgelehnt; Modus-Wechsel mit gemischtem Verlauf
  zeigt für jede Antwort die richtigen Zusatzanzeigen
  (Quellen oder SQL+Tabelle).

## Welche Hindernisse gab es und wie wurden sie gelöst

Die Implementierung selbst lief zügig und Test-getrieben. Die
Krise kam beim ersten realen App-Start. Vier Stolpersteine
nacheinander:

- **`from src import sql` schlug beim Streamlit-Aufruf fehl**:
  pytest setzt `pythonpath = .`, Streamlit nicht. `streamlit run
  src/app.py` legt nur `src/` in `sys.path`. Gelöst mit
  `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))`
  am Anfang von `app.py`, analog zu `scripts/rag_index.py`. Hätte
  ich beim ersten Wurf übernehmen müssen, weil das Pattern im
  Projekt schon etabliert war.
- **Streamlit-File-Watcher löste pyarrow-Importkette aus**:
  Default-Watcher scannt alle Module → `transformers` wird
  durchforstet → Lazy-Import sklearn → pyarrow. Auf diesem
  Windows-System mit aktiver Smart App Control / AppLocker-
  Richtlinie wird eine pyarrow-DLL geblockt. Zwei sichtbare
  Symptome: `WinError 206` aus `os.add_dll_directory` und
  `ImportError: DLL load failed ... Anwendungssteuerungsrichtlinie`.
  Gelöst mit `.streamlit/config.toml`, `fileWatcherType = "none"`.
- **pyarrow-DLL-Blockade auch ohne Watcher**: nach Watcher-Fix
  trat die DLL-Blockade beim eigentlichen Import von
  `sentence_transformers` auf, weil sklearn 1.8 in `fixes.py`
  per `try: import pyarrow / except ModuleNotFoundError` lädt –
  `ImportError` rutscht durch, weil sklearn nicht darauf prüft.
  Gelöst durch `pip uninstall pyarrow -y`. Sklearn arbeitet ohne
  pyarrow weiter, weil dann der `ModuleNotFoundError` korrekt
  abgefangen wird. Workaround in README und `requirements.txt`
  dokumentiert.
- **SQLite-Thread-Affinität**: Streamlit re-runt das Skript bei
  jedem Klick in einem anderen Thread-Pool-Worker, wir hatten die
  Connection per `@st.cache_resource` für die Session gecacht.
  Default-Verbot von `sqlite3.Connection` greift. Gelöst durch
  `check_same_thread=False` in `sql.connect`, weil wir
  ausschließlich lesen und Read-Only-Urls keine Schreib-Race-
  Conditions kennen. Multi-Thread-Test ergänzt, der die
  Eigenschaft auf Logik-Ebene absichert.

Diagnose-Verlauf-Schwäche: Bei den Folgesymptomen aus der
pyarrow-Kette habe ich zu lange an Folge-Stack-Traces
herumgeraten, statt einen direkten Reproduktionsversuch
(`python -c "import sentence_transformers"`) zu machen. Der
hätte sofort die echte Ursache (`ImportError: DLL load failed`)
gezeigt.

## Welche Erkenntnisse sind für die nächsten Schritte wichtig

- **Statische Validierung ist nicht Anwendungs-Verifikation**: ein
  „grünes Pytest plus `ast.parse`" bedeutet *nicht*, dass die App
  läuft. Bei UI-Code mit transitiven C-Extensions schon gar nicht.
  Browser-Smoke gehört zur Definition of Done bei Streamlit-
  Änderungen, kein Optional. Im globalen CLAUDE.md des Nutzers
  ist das längst dokumentiert; ich hatte es übergangen.
- **Bei Folgesymptomen direkten Original-Stack-Trace beschaffen**:
  ein `python -c "import x"` oder ein bewusst minimaler
  Reproduktionsschnipsel kostet Sekunden und schneidet
  Diagnose-Schleifen ab. Nie wieder mehrere Iterationen an einem
  Folge-Trace versuchen, ohne den Original-Trace zu kennen.
- **Lazy-Loading von schweren Ressourcen ist Pflicht** (Erkenntnis
  aus Schritt 2 bestätigt): Die `load_schema`-Cache-Resource lädt
  einmalig beim ersten SQL-Modus-Klick, nicht beim App-Start.
  Wenn der Nutzer nur RAG nutzt, fasst er die DB nie an.
- **`@st.cache_resource` über Threads**: bei Streamlit mit
  thread-affinen Ressourcen (sqlite3, file handles, locks) sofort
  die Thread-Sharing-Frage klären. SQLite löst es mit
  `check_same_thread=False` plus Read-Only. Andere Bibliotheken
  (z. B. requests-Session) haben andere Lösungen.
- **Architektur-Diskussionen vor der Implementierung lohnen sich
  weiter**: die Vorab-Klärung zu Phase 1 (App-Integration A/B/C),
  Schema-Aufbau (statisch vs. dynamisch), Konfigurations-Konsolidierung
  hat im Nachhinein Aufwand gespart. Ich hatte das in der
  Retro Schritt 2 als Lehre formuliert; in Schritt 3 angewendet,
  hat es funktioniert.
- **Drei-Fälle-Disziplin trägt auch bei Sicherheits-Validatoren**:
  bei `is_safe_select` haben die parametrisierten Erlaubt- und
  Verboten-Tests früh aufgedeckt, dass Kommentare und String-
  Literale getrennt behandelt werden müssen. Der konservative
  Ansatz „lieber falsch ablehnen als falsch durchwinken" hat
  sich als richtig herausgestellt.
- **Defense in Depth ist im Lernprojekt didaktisch wertvoll**:
  Read-Only-URI plus Whitelist plus System-Prompt-Verbot ist für
  einen Demo-Use-Case fast schon zu viel – aber genau dieses
  Übermaß macht das Sicherheitskonzept verständlich.

## Was würden wir beim nächsten Mal anders machen

- **Browser-Smoke als erster Verifikations-Schritt nach UI-Umbau**:
  vor dem ersten Stop-Punkt in `app.py` einmal echten Streamlit-
  Start machen, nicht erst beim Nutzer landen lassen.
- **Bekannte-Stolperstellen-Doku früher anlegen**: pyarrow-Block
  und Watcher-Problem in der README hätten von Anfang an stehen
  können. Bei Schritt 4 Bekannte-Stolpersteine-Abschnitt aktiv
  pflegen, nicht erst bei Krisen ergänzen.
- **`check_same_thread`-Frage beim Connection-Cache-Design
  klären**, nicht erst beim Crash. Eine Sekunde Nachdenken hätte
  das Problem antizipiert.
- **Inline-Orchestrierung in `app.py` zumindest abwägen**: für
  Schritt 4 ggf. eine reine Logik-Funktion `answer_sql_question`
  vorziehen, die auch im Mock-Client-Test verifizierbar ist.
- **Frühzeitige Anweisung an mich selbst, nicht zu raten**: im
  Diagnose-Modus „erst Reproduzieren, dann Hypothese, dann fixen"
  konsequent anwenden. CLAUDE.md verlangt das schon, ich war zu
  voreilig mit Folge-Hypothesen.

## Welche offenen Punkte werden bewusst auf später verschoben

- **Token-/Zeichen-basiertes Limit** statt fester `MAX_ZEILEN_FUER_CLAUDE`.
- **Cursor-Lifecycle und Locking** für echten Multi-User-Betrieb.
- **`answer_sql_question` als testbare Orchestrierungs-Funktion**
  in `sql.py` (mit Mock-Client) – kommt vermutlich in Schritt 4
  ohnehin natürlich, weil Claude dort selbst entscheidet.
- **Audit-Log** für Whitelist-Treffer und generierte SQLs.
- **Differenzierte Fehlerbehandlung** für Anthropic-Auth, Rate-
  Limit, Netzwerk – wie schon in Schritt 2 verschoben.
- **Echter API-Test (`test_integration_echter_api_aufruf`)**
  bewusst weiterhin geskipt; manueller Lauf bleibt die einzige
  Validierung der echten Antwort-Qualität.
- **Streamlit-Watcher mit Watchdog-Backend**: ein zweiter Anlauf
  wäre möglich, aber bei der momentanen Toolchain-Konstellation
  bröselig. Bleibt deaktiviert, bis wir frischen Bedarf haben.
- **pyarrow-Handling auf CI-/Test-Ebene**: ein automatisierter
  Check, dass pyarrow nicht installiert ist (oder zumindest sein
  Fehlen toleriert wird), würde verhindern, dass das Problem
  nach einem Reinstall stillschweigend zurückkommt. Aktuell
  rein Doku-basiert.
- **`add_message`-Bereinigung**: in der Retro Schritt 2 schon
  notiert, in Schritt 3 nicht angefasst. In Schritt 4 entscheiden,
  ob die Funktion noch gebraucht wird – sonst entfernen.

Diese Punkte sind im Code-Review (`docs/reviews/schritt_3_review.md`)
mit Begründung detaillierter aufgelistet.

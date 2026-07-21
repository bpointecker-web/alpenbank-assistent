# Retrospektive – Schritt 4: Agent mit Tool Use

Datum: 2026-04-29

## Was wurde erreicht

Der Agent läuft End-to-End:

- **`src/agent.py`** als neues, eigenständiges Modul: drei
  NamedTuples (`ToolErgebnis`, `ToolCallTrace`, `AgentAntwort`),
  Konstanten (`MODEL`, `MAX_TOKENS`, `DEFAULT_MAX_ITERATIONS`,
  `AGENT_SYSTEM_PROMPT`, `TOOL_DEFINITIONS`), Tool-Dispatcher
  (`execute_tool` mit zwei privaten Helfern) und der Multi-Turn-
  Loop (`answer_question`). Komplett ohne Streamlit-Import,
  testbar mit Mock-Client.
- **`src/app.py` komplett neu geschrieben**: Single-Chat-UI,
  Eager-Loading aller Ressourcen (ChromaDB-Collection plus
  DB-Connection plus Schema), Trace-Block-Anzeige pro
  Tool-Aufruf mit tool-spezifischen Detail-Renderern,
  Iterationslimit-Warnung. Modus-Schalter aus Schritt 3 ist weg.
- **`src/chat.py` und `tests/test_chat.py` ersatzlos gelöscht**:
  alle Schritt-1/2/3-Reste sind weg, alle Konstanten leben im
  Agent-Modul. Kommentar in `pytest.ini` von „chat" auf „agent"
  geändert, damit die Doku zum Code passt.
- **`tests/test_agent.py`** mit 35 Tests in vier Klassen:
  `TestAgentSystemPrompt`, `TestToolDefinitions`,
  `TestExecuteToolDokumentenSuche`, `TestExecuteToolDatenbankAbfrage`,
  `TestExecuteToolDispatcher`, `TestAnswerQuestion`. Mock-Client-
  Pattern für deterministische Loop-Tests ohne API-Key. Plus ein
  Test für mehrere `tool_use`-Blöcke in einer Antwort als
  Anti-Regression.
- **Test-Suite: 192 Tests grün (default), 192 grün (E2E mit
  echtem Embedding-Modell)**, Laufzeit unter einer Sekunde
  (default) bzw. 10 Sekunden (E2E).
- **Browser-Smoke aller 10 Demo-Fragen aus KONZEPT.md bestanden**:
  3 SQL, 3 RAG, 3 kombinierte, 1 Sicherheitsfrage abgelehnt. Tool-
  Wahl in jedem Fall plausibel.
- **Architektur-Skizze (`docs/schritt_4_architektur.md`) als
  Vorab-Referenz**: Klärungsfragen A1–A5 (Tool-Vertrag, Schema-
  Lokalität, Iterationslimit, Fehler-Handling, Modul-Aufteilung)
  vor dem ersten Code-Klopfen festgelegt. Hat im Lauf der Sitzung
  als Rückversicherung gedient – keine einzige Architektur-
  Entscheidung musste während der Implementierung revidiert
  werden.

## Welche Hindernisse gab es und wie wurden sie gelöst

Die Sitzung lief ohne ernste Hindernisse. Das ist ungewöhnlich
genug, dass es eine eigene Anmerkung verdient – Schritt 3 hatte
vier Browser-Crashs hintereinander. Was diesmal anders war:

- **Disziplin-Vorgabe vom Nutzer zu Beginn der Sitzung**: vor
  jeder Änderung an bestehendem Code wird die komplette Test-Suite
  ausgeführt; jede Funktion wird erst geschrieben, dann sofort
  getestet, bevor die nächste kommt; bei rotem Test zuerst
  Ursachenanalyse mit Erklärung an den Nutzer; jede Änderung wird
  vorher angekündigt. **Keine einzige dieser Disziplinen wurde
  während der Sitzung gebrochen.** Ergebnis: null Krisen, null
  Diagnose-Sackgassen.
- **Architektur-Vorab-Klärung**: A1–A5 wurden in der ersten
  Antwort festgelegt. Beim Schreiben von `execute_tool`
  („Was macht das Tool bei leerem RAG-Treffer?") gab es keinen
  Moment der Unsicherheit – Antwort A4 stand schon im Skizzendokument.
- **Schritt-3-Lehren waren noch im Kopf**: pyarrow-Workaround
  schon in der README, File-Watcher schon abgeschaltet. Streamlit
  startete beim ersten Versuch ohne DLL-Probleme.

Eine kleine Eigen-Disziplin-Lücke: Beim Streamlit-Smoke nach
Phase 2.2 habe ich ein Wakeup-Tool falsch verwendet (für eine
Aufgabe, für die es nicht gedacht ist). Folgenlos, weil das
Wakeup-Resultat nur einmalig nachgelagert eintraf, aber unsauber.
Lehre: für „warte und prüfe später" reicht
`Bash(run_in_background=true)` plus `Read` der Output-Datei –
Wakeup ist nur für `/loop`-Sequenzen.

## Welche Erkenntnisse sind für die nächsten Schritte wichtig

- **Vor-Architektur-Skizze wirkt zum dritten Mal**: in Schritt 2
  zum ersten Mal als Lehre formuliert, in Schritt 3 angewandt, in
  Schritt 4 wieder bestätigt. Bei jedem nichttrivialen Schritt
  vor dem ersten Code-Klopfen die offenen Detail-Fragen
  schriftlich klären, am besten als Markdown-Dokument zum
  Nachlesen. Kostet 10 Minuten, spart Stunden.
- **Mock-Client-Pattern für Multi-Turn-Loops ist die richtige
  Test-Architektur**: ein `MockClient` mit `responses=[...]`-
  Liste plus Helfer-Funktionen für Tool-Use-/Text-Antworten
  liefert deterministische Tests ohne API-Key. Acht von neun
  `TestAnswerQuestion`-Tests fielen in 5 Sekunden Coding pro
  Test, weil das Pattern stand.
- **Drei Verifikationsstufen statt zwei**: bisher hatten wir
  `pytest` und „Browser-Smoke". Schritt 4 hat dazwischen
  `streamlit.testing.v1.AppTest` etabliert – ein programmatischer
  Skript-Run, der Imports, Cache-Resources und das Eager-Loading
  prüft, ohne dass ein Mensch klicken muss. Das war die Lehre
  „statische Tests reichen für UI-Code nicht" aus der Schritt-3-
  Retro, jetzt mit konkretem Tool umgesetzt.
- **NamedTuples statt Dicts für Datenflüsse**: `ToolErgebnis`,
  `ToolCallTrace`, `AgentAntwort` zwingen den Code, die Felder
  bei der Konstruktion zu nennen. Tests werden lesbarer
  (`antwort.iterations_used` statt `antwort["iterations_used"]`),
  Tippfehler im Schlüsselnamen werden vom Type-Checker erkannt.
- **Tool-Beschreibungen entscheiden über die Tool-Wahl**: der
  Browser-Smoke hat 10/10 plausible Tool-Wahlen geliefert. Im
  Test wären knappe Stichworte einfacher gewesen, aber die
  ausführlichen Descriptions („Verwende dieses Tool für Fragen zu
  Zahlen: Erträge, Aufwände, Buchungen, …") tragen eindeutig zur
  Treffsicherheit bei.
- **Eager- vs. Lazy-Loading ist eine bewusste Demo-Entscheidung**:
  in Tool-Use-Apps muss Claude jederzeit beides anfassen können.
  Eager-Loading beim Start vereinfacht den Code, kostet aber den
  ersten Skript-Run. Bei einer App mit selten genutzten Tools
  wäre Lazy-Loading der saubere Weg.

## Was würden wir beim nächsten Mal anders machen

- **Wakeup-Tool nicht für „warte und prüfe später"-Aufgaben
  verwenden**: das ist ein `/loop`-Helper, kein generisches
  Sleep. Für „Streamlit braucht 30 Sekunden zum Hochfahren" ist
  `Bash(run_in_background=true)` plus späteres `Read` der
  Output-Datei das richtige Werkzeug.
- **AppTest-Smoke früher in den Workflow ziehen**: er kam in
  Schritt 4 nach dem App-Umbau. Im nächsten Schritt 5 (oder bei
  einer Folge-Iteration) gehört er **vor** den Browser-Smoke –
  als billige Vor-Verifikation, dass das Skript überhaupt durch-
  läuft. In Schritt 4 hat er sein Geld trotzdem verdient.
- **Test-Counts vorab schätzen, dann mit Reality vergleichen**:
  ich hatte für Phase 1.5 acht Tests angekündigt, neun geschrieben.
  Das ist OK, aber transparenter wäre, jede zusätzliche Test-Idee
  vorab zu nennen. Aktuell habe ich Tests „beim Schreiben gesehen"
  und nachträglich angekündigt – der Nutzer hat das angemerkt
  als „falls du das in Zukunft strenger haben willst, sag's".
  Im Zweifel lieber ein Test mehr, aber vorab erwähnt.
- **Größere Komplettrewrites trotzdem inkrementell zeigen**:
  `app.py` wurde als Komplettrewrite mit `Write` geschrieben (auf
  Wunsch des Nutzers). Bei einer Bibliothek mit vielen
  Konsumenten wäre eine Reihe kleiner `Edit`-Calls besser
  reviewbar. In Schritt 4 hat A funktioniert, weil `app.py`
  keine Importe von außen kennt.

## Welche offenen Punkte werden bewusst auf später verschoben

- **Token-/Cost-Budget pro Frage** statt nur Iterationslimit.
  Würde sauber auf einen `client.messages.create`-Wrapper passen,
  der vor und nach dem Aufruf den `usage`-Block summiert.
- **Audit-Log für Tool-Aufrufe**: SQL-Statements, RAG-Anfragen
  und ihre Ergebnisse persistieren – als JSONL-Datei oder in einer
  zweiten SQLite-DB. Hat in Schritt 3 schon auf der Liste
  gestanden, war für Schritt 4 nicht im Scope.
- **Differenzierte Fehlerklassen** für Anthropic-Auth, Rate-Limit,
  Netzwerk. Aktuell ein generisches `except Exception` in
  `app.py`. Wartet, bis solche Fehler in der Praxis auftreten.
- **Echter API-Test mit Tool-Use** als `RUN_E2E_TESTS=1`-
  markierter Smoke-Test. Würde verifizieren, dass die Anthropic-
  API tatsächlich `tool_use`-Blöcke im erwarteten Format liefert.
  Kostet API-Tokens pro Lauf.
- **Streaming der Tool-Use-Antworten**: bei langen kombinierten
  Fragen würde der Spinner nicht mehrere Sekunden stillstehen.
  Architektur-Skizze hat es out-of-Scope gestellt.
- **Lazy-Loading der schweren Ressourcen**: Embedding-Modell
  erst bei erstem RAG-Tool-Call laden. Aktuell eager beim App-
  Start. Spart bei reinen SQL-Sessions ~120 MB Modell-Download
  beim ersten Cold-Start.
- **Geld-Formatierung deterministisch im Code**: aktuell delegiert
  an Claude per System-Prompt-Regel. In Schritt 3 als Verschiebung
  notiert, in Schritt 4 nicht angefasst – passt zur Tool-Use-
  Architektur, weil Claude die Antwort selbst formuliert.
- **`history` mit Tool-Use-Sequenzen vorheriger Turns**: aktuell
  verlieren wir die SQL-/RAG-Detail-Spuren beim Folgeturn. Bei
  Folgefragen müsste Claude die SQL neu erzeugen oder aus dem
  Antworttext rekonstruieren. Funktioniert in der Praxis, ist
  aber ein Architektur-Smell.

Diese Punkte sind im Code-Review (`docs/reviews/schritt_4_review.md`)
mit Begründung detaillierter aufgelistet.

## Stand am Ende der Sitzung

Schritte 1–4 aus KONZEPT.md sind komplett. Der Lernzweck ist
erfüllt: ich habe in dieser Sitzung gesehen, wie ein Tool-Use-
Multi-Turn-Loop von innen aussieht (System-Prompt mit Schema,
Tool-Definitions als JSON-Schema, `tool_use`/`tool_result`-Block-
Konvention, Iterationslimit als Schutz). Falls eine Schritt-5-
Erweiterung kommt, sind die Topkandidaten weiterhin die Punkte
oben (Audit-Log, Token-Budget, Streaming) oder eine neue Demo-
Domäne (z. B. Buchungsstornierung mit Schreibrechten und
Confirmation-Flow).

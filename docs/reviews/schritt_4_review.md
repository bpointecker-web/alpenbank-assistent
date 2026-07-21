# Code-Review – Schritt 4: Agent mit Tool Use

Datum: 2026-04-29
Reviewer: Claude Code (selbstkritisch, gemäß CLAUDE.md)

## Was funktioniert gut

- **Saubere Schicht-Trennung**: `src/agent.py` ist komplett ohne
  Streamlit-Import. Der Multi-Turn-Loop ist mit reinem Mock-Client
  vollständig testbar – kein API-Key, keine ChromaDB, kein Browser
  nötig. Das war eine bewusste Lehre aus Schritt 3 (Inline-
  Orchestrierung in `app.py` blockierte Headless-Tests).
- **Drei klar getrennte NamedTuples**: `ToolErgebnis`,
  `ToolCallTrace`, `AgentAntwort` haben jeweils einen genau
  definierten Zweck (`ToolErgebnis.text` geht an Claude,
  `details` an die UI). Die Datenstruktur erzwingt, dass diese
  Trennung im Code nicht versehentlich aufweicht.
- **Defense in Depth bleibt gewahrt**: die drei Schichten gegen
  Schreibzugriffe aus Schritt 3 sind alle drin – Read-Only-URI in
  `sql.connect`, Whitelist in `is_safe_select`, Verbot im
  `AGENT_SYSTEM_PROMPT`. Bei einem Whitelist-Verstoß bekommt
  Claude den Fehler als `tool_result` mit `is_error=True` zurück
  und kann im nächsten Turn höflich ablehnen oder korrigieren.
- **Mock-Client-Test-Architektur deckt 9 Loop-Szenarien ab**:
  keine Tool-Nutzung, ein Tool-Aufruf, zwei sequenzielle Aufrufe,
  zwei Aufrufe in EINER Antwort, Iterationslimit, Tool-Fehler-
  Durchreichung, Mutations-Schutz der `history`, Schema-Einsetzung
  in den System-Prompt, unerwarteter Stop-Grund. Plus die
  `execute_tool`-Tests pro Tool und Fehlerfall.
- **Vorab-Architektur-Skizze (`docs/schritt_4_architektur.md`)
  hat fünf Detail-Entscheidungen vorab geklärt** und sich im
  Implementierungs-Verlauf nicht ein einziges Mal als falsch
  erwiesen. Dritte Bestätigung in Folge, dass die Skizze vor
  Code-Klopfen Aufwand spart.
- **Komplettes Aufräumen**: `src/chat.py` und `tests/test_chat.py`
  sind ersatzlos weg, alle Konstanten leben in `src/agent.py`.
  Keine versteckten Toten-Code-Reste, kein „in Schritt 5
  vielleicht wieder gebraucht"-Aufschub.
- **`AppTest`-Skript-Run als zusätzliche Verifikationsstufe**:
  zwischen `pytest` und Browser-Smoke gibt es jetzt einen dritten
  Layer, der das Streamlit-Skript programmatisch durchläuft. Hat
  in Schritt 4 die Imports und das Eager-Loading der Ressourcen
  vor dem Browser-Smoke abgedeckt – Lehre aus den Schritt-3-Krisen
  in der Praxis angewendet.
- **End-to-End im Browser bestätigt**: alle 10 Demo-Fragen aus
  KONZEPT.md geliefert (3 SQL, 3 RAG, 3 kombinierte, 1 Sicherheit
  abgelehnt). Tool-Wahl in jedem Fall plausibel.

## Wo der einfachste Weg gewählt wurde, der später zum Problem werden könnte

### 1. `MAX_AGENT_ITERATIONS = 5` ist eine Bauchzahl

Wir limitieren rein auf Schleifendurchläufe, nicht auf
Token-Verbrauch oder Wallclock-Zeit. Eine Frage, die Claude in
4 Iterationen mit 4 großen Tabellen-Tool-Results bearbeitet,
verbrennt mehr Tokens als 10 leichte Iterationen.

Bewusst akzeptiert: für die Demo-Fragen funktioniert das Limit;
keine der 10 Fragen hat mehr als 3 Iterationen gebraucht. Saubere
Lösung wäre ein Token-Budget plus Iterationslimit als doppelter
Schutz.

### 2. Tool-Beschreibungen sind lang und doppeln den System-Prompt

Die Tool-Wahl-Heuristik („Regeln/Prozesse → dokumenten_suche,
Zahlen → datenbank_abfrage") steht sowohl in den Tool-
Descriptions als auch im `AGENT_SYSTEM_PROMPT`. Defense in Depth
gegen Tool-Verwechslungen, aber:

- Wer eine Stelle ändert, muss daran denken, die andere mitzuziehen
- Token-Kosten pro Aufruf sind merklich (Tool-Definitions werden
  mitgeschickt)

Im Lernprojekt akzeptiert, weil empirisch wirksam. Im Produkt-Code
würde man entweder die Description knapp halten oder den System-
Prompt entlasten.

### 3. Tool-Output-Strings ohne Token-Limit zurück an Claude

`format_result_for_claude` schneidet bei `MAX_ZEILEN_FUER_CLAUDE
= 50` ab; `format_context` liefert die ChromaDB-Treffer in voller
Länge. Bei einem Treffer mit 5000 Zeichen Inhalt × 5 Treffern
gehen 25 KB als Tool-Result an Claude.

Bei den Bank-Demo-Dokumenten (1–3 Seiten je) unkritisch. Bei
echten Wissensbasen müsste der Tool-Output token-bewusst
abgeschnitten werden.

### 4. `dict(block.input)` wird zwei Mal nebeneinander kopiert

Im Loop-Body kopiere ich `block.input` einmal beim Aufruf von
`execute_tool` und einmal beim Anlegen der `ToolCallTrace`. Eine
einzige lokale Variable `tool_input = dict(block.input)` wäre
DRY-konform und doppelt so klar.

Mini-Schmerzpunkt, defensiver als nötig. Bewusst stehengelassen,
weil die Korrektur den Code nicht spürbar verbessert.

### 5. UI rendert synchron, kein Streaming

Während Claude einen Tool-Use-Loop durchläuft, sieht der Nutzer
nur den Spinner – nicht den Zwischenstand („gerade SQL ausgeführt,
suche jetzt in den Dokumenten …"). Tool-Use-Streaming wäre über
die Anthropic-Streaming-API möglich, vervielfacht aber die
Implementierungskomplexität.

Bewusst out-of-Scope laut Architektur-Skizze; bei langen
kombinierten Fragen aber spürbar, dass der Spinner mehrere
Sekunden steht.

### 6. `history` ohne frühere Tool-Use-Sequenzen

Der Multi-Turn-Loop bekommt aus der UI nur User/Assistant-Texte.
Frühere Tool-Use- und Tool-Result-Blöcke werden nicht
mitgeschickt. Konsequenz: bei einer Folgefrage „und das gleiche
für 2024?" hat Claude die SQL-Abfrage aus dem vorigen Turn nicht
mehr direkt vor sich – nur den fertigen Antworttext. Reicht in der
Praxis, weil Claude das SQL aus dem Antworttext rekonstruieren
oder neu erzeugen kann.

### 7. Generischer Exception-Catch in `app.py`

```python
except Exception as exc:
    st.error(f"Fehler bei der Beantwortung: {exc}")
    st.stop()
```

Schluckt jeden Fehler ohne Differenzierung – Auth-Fehler,
Rate-Limit, Netzwerk, ChromaDB-Korruption sehen für den Nutzer
gleich aus. Bewusst akzeptiert, weil spezifische Fehlerklassen
erst im Betrieb auftreten würden. Bei Beobachtung in der Praxis
nachschärfen.

## Welche Annahmen wurden getroffen, die der Nutzer prüfen sollte

- **Anthropic-Tool-Use-API liefert `block.input` als
  serialisierbares Dict**: in der Praxis bei den 10 Demo-Fragen
  bestätigt. Wenn die SDK irgendwann Pydantic-Objekte statt Dicts
  liefert, würde `dict(block.input)` schon scheitern. Test 7
  (`test_normalfall_schema_wird_in_system_prompt_eingesetzt`)
  fängt das nicht ab, weil Mock-Antworten Dicts verwenden.
- **`block.id` ist immer vorhanden**: kein `getattr`-Fallback.
  Bei abweichendem SDK-Verhalten würde der Loop mit AttributeError
  sterben. Im Code-Review bewusst stehengelassen (siehe Phase-1-
  Review zwischen uns).
- **5 Iterationen reichen für jede Demo-Frage**: in 10/10 Fällen
  bestätigt, aber das Sample ist klein. Bei Fragen, die mehrere
  Quartale × mehrere Kostenstellen × mehrere Richtlinien kombinieren,
  könnte das Limit anschlagen. Limit-Hinweis-Text klärt den Nutzer
  darüber auf.
- **Eager-Loading aller Ressourcen beim App-Start**: Embedding-
  Modell wird beim ersten Skript-Run geladen, auch wenn der Nutzer
  nur SQL-Fragen stellt. Akzeptabel im Demo-Use-Case; bei
  Cold-Starts oder ressourcenarmen Hosts spürbar.
- **`traces`-NamedTuples in `st.session_state.messages` bleiben
  über Re-Runs stabil**: Streamlit serialisiert NamedTuples im
  Session-State. Funktioniert in der Praxis. Bei einem Streamlit-
  Update mit verändertem Session-State-Format wäre das eine
  Falle.

## Sicherheitslücken und Fehlerfälle, die nicht abgedeckt sind

1. **Keine Token-/Cost-Begrenzung pro Antwort**: bei einer Frage,
   die Claude in fünf Iterationen mit jeweils großen Tool-Results
   bearbeitet, entstehen merkliche Kosten. Kein API-Limit, kein
   App-seitiger Token-Counter.
2. **Kein Audit-Log der Tool-Aufrufe**: SQL-Abfragen, RAG-Anfragen,
   ihre Ergebnisse und Fehler werden nur in `st.session_state.messages`
   gehalten. Beim Schließen des Tabs sind sie weg – keine
   Nachvollziehbarkeit, was über die Datenbank gelaufen ist.
3. **Tool-Result-Texte können beliebig lang sein**: ein
   manipulierter Dokumenten-Inhalt mit eingebettetem
   „SYSTEM:"-Trick könnte als RAG-Treffer in den Kontext landen.
   Prompt-Injection ist eine bekannte Angriffsfläche bei RAG.
   Mitigated nur durch unsere kontrollierten Demo-Dokumente.
4. **Iterationslimit-Erreichen wird zwar dem Nutzer gemeldet, aber
   der Antworttext zeigt nicht, wie weit Claude kam**: die Traces
   sind sichtbar, aber der eigentliche Antwortbereich enthält nur
   die Limit-Meldung. Bessere UX wäre, den letzten Assistant-
   Text-Block mit anzuzeigen.
5. **Keine Eingabe-Sanitisierung der Nutzerfrage**: ein Nutzer
   könnte selbst einen Pseudo-System-Prompt eingeben. Claude ist
   gegenüber solchen Versuchen relativ robust, aber wir haben es
   nicht getestet.
6. **Mehrfache `tool_use`-Blöcke in EINER Antwort werden
   sequentiell ausgeführt**, nicht parallel. Performance-Smell bei
   Tools, die echte I/O-Latenz haben. SQLite und ChromaDB sind
   beide schnell, kein Schmerz; bei z. B. einer Web-Recherche-
   Tool wäre das anders.

## Was würde ein erfahrener Senior-Entwickler kritisieren

- **`app.py` ist 250 Zeilen Skript-Stil**: alle UI-Helper
  (`render_message`, `render_trace`, `_render_dokumenten_suche_details`,
  `_render_datenbank_abfrage_details`, `_format_tool_input`,
  `history_for_agent`) leben global im Modul. Sauberer wäre ein
  `src/ui_helpers.py`, das `app.py` importiert. Im Lernprojekt-
  Kontext akzeptabel, weil Streamlit-Skripte typischerweise so
  aussehen.
- **`history_for_agent` filtert auf `("user", "assistant")`**:
  würde leise scheitern, wenn jemals Tool-Result-Messages in
  `st.session_state.messages` landen würden. Aktuell unmöglich,
  aber kein Defensivchecker.
- **Kein E2E-Test mit echtem Tool-Use-API-Call**: alle Loop-Tests
  sind gegen `MockClient`. Bei einer Anthropic-API-Änderung
  (Tool-Use-Format-Anpassung) würden wir es erst im Browser
  merken. Ein `RUN_E2E_TESTS=1`-markierter Tool-Use-Smoke wäre
  möglich, kostet aber API-Tokens pro Lauf.
- **Trace-Anzeige zeigt Tool-Input mit `repr(v)`**: bei
  Strings mit Umlauten oder Zeilenumbrüchen wirkt die Ausgabe
  technisch (`'Wie viel\\n…'`). `json.dumps(..., ensure_ascii=False)`
  wäre lesbarer.
- **Eager-Loading verzögert den ersten App-Start spürbar**:
  Embedding-Modell + ChromaDB + DB-Schema werden alle beim ersten
  Skript-Run geladen. Lazy-Loading nur bei tatsächlichem Tool-
  Aufruf wäre eleganter, würde aber Streamlit-Caching aufbrechen.
- **Keine strukturierten Logs für Iterations-Verlauf**: bei einer
  Tool-Use-Schleife, die unerwartet das Limit erreicht, müsste
  der Nutzer im Code Print-Statements einbauen. Ein leichtgewichtiges
  `logging.getLogger("agent")` mit DEBUG-Level würde das lösen.

## Zusammengefasst

Schritt 4 ist funktional komplett: Tool-Use-Loop mit Multi-Turn-
Handling, Mehrfach-Tool-Use-Blöcke, Iterations-Limit, Schema-Einsatz,
Fehler-Durchreichung, Multi-Tool-Trace-Anzeige. **192 Tests grün
(default und E2E), Browser-Smoke aller 10 Demo-Fragen aus
KONZEPT.md bestätigt.** Schritte 1–4 aus KONZEPT.md sind damit
durchgängig abgedeckt.

Die größten echten Schwächen:

- Kein Token-/Cost-Budget, nur Iterationslimit
- Tool-Output ohne Token-Counting
- Kein Audit-Log
- Generischer Exception-Catch in der UI

Plus eine erfreuliche Beobachtung: die Disziplin aus der
Schritt-4-Eingangsbesprechung („vor jeder Änderung pytest, jede
Funktion sofort testen, bei rotem Test erst Ursache analysieren")
hat in dieser Sitzung **null Krisen** produziert. Krasser Kontrast
zu den vier Browser-Crashs in Schritt 3. Adressiert in der
Retrospektive.

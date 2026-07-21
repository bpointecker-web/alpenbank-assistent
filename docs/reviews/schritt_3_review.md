# Code-Review – Schritt 3: SQL-Teil

Datum: 2026-04-28
Reviewer: Claude Code (selbstkritisch, gemäß CLAUDE.md)

## Was funktioniert gut

- **Saubere Schicht-Trennung**: `src/sql.py` ist komplett ohne
  Streamlit- oder Anthropic-Importe. Auch der zweite Claude-Aufruf
  bleibt aus dem Modul draußen – die Orchestrierung lebt in
  `app.py`, konsistent zur RAG-Konvention.
- **Defense in Depth gegen Schreibzugriffe**: Read-Only-URI
  (`mode=ro` in `connect`) **und** SELECT-Whitelist
  (`is_safe_select`) **und** System-Prompt-Verbot. Erst wenn alle
  drei Schichten knacken, käme ein Schreibversuch durch. Das
  pretty-much-can't-happen-Setup ist im Lernprojekt didaktisch
  wertvoll.
- **Whitelist behandelt Kommentare und String-Literale getrennt**:
  ein verbotenes Keyword in einem SQL-Kommentar (`-- DELETE later`)
  oder in einem Wert (`name = 'Delete-Service'`) blockiert das
  Statement nicht. Tests parametrisiert über 8 Erlaubt- und
  13 Verboten-Fälle.
- **`QueryResult`-NamedTuple**: explizite `rows`/`columns`-Trennung
  hält die Spalten-Information auch bei leerem Ergebnis erhalten.
  Kleiner Aufwand, klare Vertrags-Form.
- **Multi-Thread-Test schließt die `check_same_thread`-Lücke**:
  nach der Krise heute Nachmittag gibt es jetzt einen expliziten
  Test, der die Streamlit-Worker-Pool-Eigenschaft auf Logik-Ebene
  absichert. Drei-Fälle-Disziplin wurde damit auch für den
  Thread-Aspekt komplett.
- **End-to-End im Browser bestätigt**: alle drei reinen SQL-Demo-
  Fragen funktionieren, Sicherheitsfrage 10 wird korrekt
  abgelehnt, RAG-Modus läuft als Regression weiter, Modus-Wechsel
  mit gemischtem Verlauf zeigt die richtigen Anhänge.

## Wo der einfachste Weg gewählt wurde, der später zum Problem werden könnte

### 1. `is_safe_select` ist kein echter SQL-Parser

Die Bereinigung über zwei Regex-Schritte (Kommentare entfernen,
String-Literale neutralisieren) ist eine Heuristik. Konkrete
Schwächen:

- SQL-Strings mit Escape-Quote (`'don''t'`) werden vom
  einfachen `'[^']*'`-Regex falsch zerlegt – die Funktion könnte
  ein gültiges Statement fälschlich ablehnen.
- Statement mit Operator `;` innerhalb eines String-Literals wird
  auf jeden Fall blockiert, auch wenn es semantisch ein
  Single-Statement ist.
- Doppelt-Quoted-Identifier mit reserviertem Wort darin
  (`SELECT "DELETE" FROM …`) würden geblockt.

Bewusst akzeptiert: konservativ falsch ablehnen ist besser als
falsch durchwinken. Dokumentiert im Docstring. Eine echte
Lösung wäre ein Mini-Lexer, für ein Lernprojekt overkill.

### 2. `MAX_ZEILEN_FUER_CLAUDE = 50` ist eine Bauchzahl

Wir limitieren rein auf Zeilenzahl, nicht auf Token-Verbrauch.
Eine Tabelle mit 50 sehr breiten Zeilen verbrennt mehr Tokens
als 200 schmale. Konsequenzen:

- Token-Limit-Überschreitungen bei breiten Spalten möglich.
- Kein adaptives Verhalten je nach Spaltenbreite.

Saubere Lösung: tatsächlichen Zeichen-/Token-Bedarf zählen,
adaptiv abschneiden. Bei den drei Bank-Tabellen unkritisch.

### 3. Connection und Cursor werden zwischen Threads geteilt

`check_same_thread=False` plus geteilter Connection bedeutet:
zwei nebenläufige Streamlit-Klicks könnten gleichzeitig
`connection.execute(...)` aufrufen. SQLite serialisiert intern,
aber Cursor-Lebenszyklen könnten sich gegenseitig stören
(`fetchall` während ein anderer Thread `execute` neu aufruft).

Im Single-User-Lernprojekt nahezu ausgeschlossen, weil Streamlit
pro Session nur eine Frage gleichzeitig verarbeitet. In einem
Multi-User-Setup wäre die richtige Lösung: Connection-Pool oder
Connection pro Thread.

### 4. Inline-Orchestrierung in `app.py`

`beantworte_sql_frage` lebt in `app.py`, nicht in `sql.py`.
Vorteil: konsistent zu `rag`-Modus. Nachteil: Headless-Tests der
Orchestrierung sind nicht möglich. Wenn wir eines Tages doch
einen Mock-Client-Integrationstest wollen, müssten wir die
Funktion herausziehen.

### 5. Geldformatierung delegiert an Claude

Statt deterministisch im Code (Spalte erkennen → `f"{x:,.2f} €"`)
lassen wir Claude die deutsche Geldformatierung selbst machen.
Vorteil: Claude erkennt automatisch, welche Spalten Geld sind.
Nachteil:

- Nicht reproduzierbar – Claude könnte gelegentlich ein
  abweichendes Format wählen.
- Kostet Tokens und einen ganzen zweiten API-Call mit dazu.

Für einen Lernprojekt-Demo ok, für ein Reporting-Tool zu wackelig.

### 6. Doppelte User-Message-Builder

`build_user_message_with_context` (RAG) und
`build_user_message_with_schema` (SQL) sind strukturell
identisch – `f"{kontext}\n\nFrage: {frage}"`. Ein gemeinsamer
Helper mit Bezeichnungs-Parameter wäre DRY-konform, aber bei
zwei Aufrufern noch keine Schmerzgrenze.

## Welche Annahmen wurden getroffen, die der Nutzer prüfen sollte

- **Claude liefert SQL in `\`\`\`sql`-Codeblöcken**: in der Praxis im
  Browser bestätigt, aber nur an einem Modell und einem Wortlaut
  des System-Prompts. Falls sich Claude-Verhalten ändert (anderes
  Modell, andere Sprachversion), könnte der Parser regressieren.
  Der Fallback auf nackten SQL-Text fängt einiges davon ab.
- **Schema mit zwei Beispielzeilen reicht für gute SQL-Generierung**:
  bei drei Tabellen funktioniert. Bei komplexerem Schema mit vielen
  Joins müsste man Beispiel-Queries oder Foreign-Key-Diagramme
  ergänzen.
- **`SQL_ANSWER_SYSTEM_PROMPT` erkennt Geld-Spalten zuverlässig**:
  bei „betrag" funktioniert der Trigger; bei einer Spalte
  „kosten" oder „eur" könnte Claude die Erkennung verfehlen und
  Zahlen ohne Formatierung ausgeben.
- **`(weitere X Zeilen abgeschnitten)`-Marker wird respektiert**:
  Claude soll daraus *nicht* schließen, dass er weitere Daten
  anfordern muss (er kann es ohnehin nicht). In den getesteten
  Fällen kein Problem; bei Edge-Cases unklar.
- **Eine globale Connection für die ganze App-Session reicht**:
  setzt voraus, dass die DB-Datei während der Session nicht
  ausgetauscht wird. Wer `daten_erzeugen.py` neu laufen lässt,
  während die App läuft, sieht alte Daten.

## Sicherheitslücken und Fehlerfälle, die nicht abgedeckt sind

1. **Whitelist-Bypass durch ungewöhnliche Whitespace-Zeichen**:
   wir tokenisieren mit `\w+`. Nicht-ASCII-Whitespace zwischen
   Tokens (z. B. Zero-Width-Space) wird als Trenner erkannt; das
   ist gut. Aber: ein nicht-ASCII-Zeichen *innerhalb* eines
   Schlüsselworts könnte den Wort-Match brechen (`DEL​ETE`
   wäre kein `DELETE`-Token). Theoretisch, in der Praxis nicht
   zu konstruieren, weil SQLite das Statement ohnehin ablehnt.
2. **Keine Rate-Limit- oder Cost-Begrenzung**: jede SQL-Frage
   löst **zwei** Anthropic-Calls aus statt einen wie bei RAG.
   Token-Verbrauch verdoppelt sich. Bei Fehlbedienung (Spam-
   Klicken) entstehen Kosten ohne Schutz.
3. **Fehlermeldungen aus `sqlite3.OperationalError` werden direkt
   in den Chat geschrieben** – inklusive Tabellennamen und
   Spaltennamen. Bei einer fiktiven Bank-Demo egal, in einem
   Produkt-System wäre das eine Information-Disclosure.
4. **Connection wird nicht im atexit/finally geschlossen**:
   `@st.cache_resource` cached die Connection, schließen wir nie
   explizit. Streamlit cleant beim Session-Ende auf, aber bei
   einem Crash bleibt der File-Lock theoretisch hängen.
5. **`check_same_thread=False`-Markierung gilt jetzt für alle
   Aufrufer von `sql.connect`**: nicht nur für die App. Wer
   `sql.connect` für einen Schreib-Use-Case missbrauchen
   würde, verliert die Default-Schutzschicht. Mitigated durch
   Read-Only-URI (Schreiben würde ohnehin scheitern).
6. **pyarrow-Workaround ist nicht durch Tests abgesichert**: wer
   nach `pip install -r requirements.txt` vergisst, pyarrow zu
   deinstallieren, läuft wieder in den DLL-Block. Die README
   warnt, aber kein Mechanismus erzwingt es.

## Was würde ein erfahrener Senior-Entwickler kritisieren

- **Streamlit-File-Watcher abgeschaltet**: Hot-Reload ist ein
  Produktivitäts-Feature. Workaround `fileWatcherType = "none"`
  ist eine Brechstange. Sauberer wäre `fileWatcherType =
  "watchdog"` plus `serverIgnoreModules`-Liste, falls möglich.
- **Connection-Lifecycle**: keine kontextmanaged Verbindung,
  kein finally-close in `open_db`. Bei länger laufenden Sessions
  oder Tests-Reuses kann das Datei-Handle hängen.
- **Inline-Orchestrierung verhindert headless Integration-Tests**:
  ein Refactoring zu `answer_sql_question(client, connection,
  schema, frage)` in `sql.py` mit Mock-Client würde die
  Browser-only-Verifikation ersetzen können.
- **Keine strukturierten Logs**: Whitelist-Treffer, generierte
  SQLs und SQLite-Fehler verschwinden im UI. Für ein produktives
  System wäre ein Audit-Trail (welche Frage → welches SQL → wie
  viele Zeilen → wie lange) Pflicht.
- **Zwei Claude-Aufrufe pro Frage** sind ein Architektur-Smell.
  In Schritt 4 (Tool Use) wird das natürlich vereint, weil Claude
  Tool-Result und Antwort in einem Multi-Turn macht. Im Übergangs-
  Schritt 3 ist das aber unschön.
- **Geld-Formatierung im Prompt** statt im Code: Senior würde
  „nicht reproduzierbar, halt das aus dem LLM raus" sagen.
  Pragmatik schlägt Reinheit hier nur, weil Spaltenerkennung im
  Code aufwändig wäre.

## Zusammengefasst

Schritt 3 ist funktional komplett und zwei Verteidigungslinien
gegen Schreibzugriffe stehen. 196 Tests grün, alle vier reinen
SQL-Demo-Fragen aus KONZEPT.md im Browser bestätigt. Die
größten echten Schwächen sind:

- Whitelist ist Heuristik, kein Parser.
- Geteilte Connection ohne Lock funktioniert nur im Single-User-
  Modus.
- Geldformatierung delegiert an LLM.

Plus eine Disziplin-Lücke, die sich in den heutigen Krisen
gezeigt hat: statische Tests reichen für UI-Code nicht.
Adressiert in der Retrospektive.

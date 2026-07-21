# Code-Review – Schritt 2: RAG-Teil

Datum: 2026-04-26
Reviewer: Claude Code (selbstkritisch, gemäß CLAUDE.md)

## Was funktioniert gut

- **Klare Trennung Logik / UI**: `src/rag.py` ist komplett ohne
  Streamlit- oder Anthropic-Importe. Jede der sieben Funktionen lässt
  sich isoliert testen.
- **Embedding-Modell wird nicht im Modul-Import geladen**: durch den
  Lazy-Loader `get_default_embedding_function` bleibt die Test-Suite
  bei 0,07 s. Bei naiver Implementierung wäre allein der Import von
  `src.rag` ~10 s teuer geworden.
- **Echte Pipeline ist verifiziert**: zwei E2E-Tests
  (`test_e2e_index_und_suche_finden_thematisch_passenden_chunk` und
  `test_e2e_build_index_persistiert_und_indexiert`) decken den
  kompletten Round-Trip von Indexierung über Suche bis Treffer-Format
  ab. Aktivierbar per `RUN_E2E_TESTS=1`.
- **Drei-Fälle-Disziplin durchgängig**: alle Funktionen haben
  Normal-, Rand- und Fehler-Tests. 90 Tests grün, 3 standardmäßig
  übersprungen.
- **Saubere Fehlermeldungen beim ersten App-Start**: fehlt
  `data/chroma/` oder die Collection, gibt es einen klaren Hinweis
  auf das Indexierungs-Skript statt eines kryptischen Stack-Traces.

## Wo der einfachste Weg gewählt wurde, der später zum Problem werden könnte

### 1. Dokumente sind zu kurz – Chunking entfaltet keinen Nutzen

Die fünf fiktiven Richtlinien sind alle unter 500 Wörtern. Ergebnis
des realen Indexlaufs: **5 Dokumente → 5 Chunks**. Das gesamte
500-Wort-mit-50-Overlap-Chunking ist auf den aktuellen Daten ein
No-op.

Konsequenzen:
- Die Demo zeigt das RAG-Konzept nicht in voller Stärke. Ein
  externer Beobachter könnte fragen, wozu das Chunking überhaupt
  da ist.
- Overlap-Effekte (Antwort an Chunk-Grenze) sind nicht
  beobachtbar.
- Der Lerneffekt für „wie wirken Chunk-Größen?" ist gering.

Lösungsoptionen für später: längere Dokumente generieren (z. B.
2000–3000 Wörter pro Richtlinie) oder die Chunk-Größe auf z. B.
100 Wörter senken, um auf den aktuellen Daten mehrere Chunks pro
Dokument zu erzeugen. Würde ich erst angehen, wenn Schritt 3 läuft.

### 2. `chat.add_message` ist in der RAG-App toter Code

`add_message` wurde in Schritt 1 sorgfältig getestet (5 Tests,
Immutability garantiert). In der neuen `app.py` wird die Funktion
**nicht mehr verwendet** – wir hängen direkt an
`st.session_state.messages` an, weil wir das Zusatzfeld `sources`
brauchen.

Folgen:
- Inkonsistenz: einmal API-Aufruf, einmal direkt am State.
- Wartungsfalle: wenn jemand `add_message` ändert (z. B.
  Validierung erweitert), bleibt die App-Logik unberührt.
- Tests erzeugen falsche Sicherheit für die App.

Saubere Lösung: Entweder `add_message` so erweitern, dass es
zusätzliche Felder akzeptiert (z. B. via `**extras`), und in
`app.py` konsequent nutzen – oder die Funktion ersatzlos
entfernen, sobald sicher ist, dass Schritt 4 sie auch nicht
mehr braucht.

### 3. Doppelte Render-Logik für Quellen in `app.py`

Die Anzeige der Treffer-Liste passiert an zwei Stellen: einmal in
`render_message` für persistierte Historie, einmal direkt im
`if user_input`-Block für die frische Antwort. Beide Blöcke sind
inhaltlich identisch (Quelle, Distanz, 300-Zeichen-Auszug).

Ursache: Streamlit-Rendering. Beim Re-Run werden alle Messages
gerendert *bevor* die neue Frage verarbeitet wird, also muss die
neue Antwort separat gerendert werden.

Saubere Lösung: gemeinsame Helper-Funktion `render_sources(treffer)`,
die beide Stellen verwenden. Hätte ich beim ersten Wurf machen
sollen; ich habe es bewusst dupliziert, um die Logik klarer zu
sehen, und es dann nicht mehr aufgeräumt.

### 4. Breite Exception-Behandlung in `app.py`

`except Exception as exc` fängt alles – ChromaDB-Fehler,
Embedding-Fehler, Anthropic-Auth-Fehler, Anthropic-Rate-Limit,
Netzwerkfehler. Im aktuellen Lernprojekt ok, aber:

- Versteckt unterschiedliche Fehlerursachen hinter einer einzigen
  generischen Meldung.
- Gibt dem Nutzer keine handlungsrelevante Information
  („Rate Limit erreicht, versuche es in 60 s erneut" ist hilfreicher
  als „Fehler beim Aufruf").

Würde ich in Schritt 4 oder spätestens vor jeder „echten" Nutzung
differenzieren.

## Welche Annahmen wurden getroffen, die der Nutzer prüfen sollte

- **Mehrsprachiges Modell ist die richtige Wahl für deutsche
  Bank-Texte**: Annahme basiert auf der allgemeinen Beobachtung,
  dass `paraphrase-multilingual-MiniLM-L12-v2` deutsche Synonyme
  besser erkennt als `all-MiniLM-L6-v2`. Bei den fünf Test-Fragen
  funktioniert es; eine systematische Evaluation gibt es nicht.
  Im Konzept ist das auch nicht gefordert.
- **1-Turn-Konversation ist akzeptabel für den Nutzer**: bewusste
  Vereinfachung in der Diskussion bestätigt. Folgefragen wie *"und
  was gilt für Verpflegung?"* funktionieren nicht – Claude sieht den
  vorigen Turn nicht.
- **Strikter „nur aus Kontext"-System-Prompt ist gewünscht**: in
  der Diskussion bestätigt. Heißt im Umkehrschluss: der Assistent
  beantwortet keine Allgemeinwissensfragen mehr, auch wenn er sie
  könnte.
- **Quelle in Metadaten und nicht aus ID parsen** ist
  zukunftssicher: gilt nur, wenn niemand jemals Dateinamen mit `#`
  einführt. Test-Datei `test_normalfall_quelle_landet_in_metadaten_nicht_in_id_geparst`
  schützt aktiv vor versehentlicher Wegoptimierung.
- **`reset_collection` per `list_collections`-Check** ist
  version-unabhängig: gilt, solange ChromaDB die `list_collections`-API
  beibehält. Tradeoff: ein zusätzlicher API-Aufruf pro Reset, aber
  robust gegen Exception-Klassen-Renames.

## Sicherheitslücken und Fehlerfälle, die nicht abgedeckt sind

1. **Kein XML-Escaping in `format_context`**: wenn ein Dokument
   `</chunk>` oder `</kontext>` enthielte, würde Claude den
   Kontextblock falsch parsen. Bei aktuellen Bank-Texten unmöglich,
   bei späterem Indexieren von Markdown- oder HTML-Quellen aber
   ein Risiko. Im Docstring vermerkt.
2. **Keine Längen-Begrenzung des Kontexts**: bei sehr vielen oder
   sehr großen Treffern könnten wir Anthropic-Kontext-Limits sprengen.
   Für die Demo unkritisch (5 Treffer × ~500 Wörter), würde aber
   bei größeren Indizes zum Problem.
2. **Keine Eingaben-Sanitization**: Nutzereingaben gehen ungefiltert
   in `collection.query`. ChromaDB führt selbst keinen SQL-artigen
   Code aus, daher kein Injection-Risiko – wohl aber theoretischer
   Prompt-Injection-Vektor (eine Frage wie „Ignoriere alle vorigen
   Anweisungen ..." wandert direkt in die User-Message).
3. **Keine Rate-Limit- oder Cost-Begrenzung**: jede Frage löst
   einen Anthropic-Call aus. Bei Fehlbedienung (z. B. Endlosschleife
   im Browser) entstehen Kosten ohne Schutz.
4. **`@st.cache_resource` cached die Collection für die Session**:
   wenn `rag_index.py` während laufender App neu indiziert wird,
   sieht die App die neue Collection nicht. Nutzer muss die App neu
   starten. Nicht offensichtlich, aber im Lernprojekt akzeptabel.
5. **Pfad-Hardcoding**: `Path("data/chroma")` als Modul-Konstante
   in beiden Skripten setzt voraus, dass alles aus dem Projekt-Root
   ausgeführt wird. Wer in einem Unterordner startet, scheitert.

## Was würde ein erfahrener Senior-Entwickler kritisieren

- **Zu viel Logik in `app.py`**: die Verkettung Suche → Format →
  Build-Message → Send → Display lebt direkt im UI-Code. Sauberer
  wäre eine Funktion `answer_question(client, collection, frage)
  -> (antwort, treffer)` in einem eigenen Modul – ist auch
  testbar, spart die manuelle Browser-Verifikation.
- **Streamlit-Logik nicht abgedeckt**: keine einzige Test-Zeile
  für `app.py`. Üblich (Streamlit ist schwer testbar), aber
  bedeutet: Integrations-Bugs werden nur durch manuellen Test
  entdeckt. Eine kleine Headless-Test-Variante mit dem
  vorgeschlagenen `answer_question`-Refactoring wäre möglich.
- **`build_user_message_with_context` mischt zwei Zustände**:
  bei vorhandenem Kontext anderes Format als bei leerem Kontext.
  Trennung in zwei Funktionen oder ein expliziter
  `KontextErgebnis`-Typ wäre transparenter.
- **Konstanten verteilt**: `EMBEDDING_MODELL` in `rag.py`,
  `MODEL` in `chat.py`, `CHROMA_PATH` in `app.py`, `DOC_DIR` in
  zwei Skripten. Eine zentrale `config.py` würde Klarheit schaffen,
  ist aber für ein Lernprojekt overkill.
- **Keine Strukturierung der Sourcen-Anzeige**: 300-Zeichen-Cut
  ist willkürlich. Bei längeren Chunks würde man besser einen
  „Highlight-Window" um die Trefferregion zeigen.

## Zusammengefasst

Schritt 2 funktioniert vollständig und ist sauber getestet. Die
größten Schwächen sind keine Bugs, sondern bewusste oder
unbewusste Vereinfachungen, die in Schritt 3 oder spätestens vor
einer produktiven Nutzung adressiert werden sollten – allen voran
die toten Helfer-Funktionen, die doppelte Render-Logik und die
zu kurzen Demo-Dokumente.

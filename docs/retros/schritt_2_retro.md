# Retrospektive – Schritt 2: RAG-Teil

Datum: 2026-04-26

## Was wurde erreicht

Der RAG-Teil läuft End-to-End:

- Sieben reine Logik-Funktionen in `src/rag.py` (Loading, Chunking,
  ID-Vergabe, Collection-Anlage, Indexierung, Suche, Kontext-Format),
  jeweils mit Drei-Fälle-Tests.
- Indexierungs-Skript `scripts/rag_index.py`, das eine persistente
  ChromaDB unter `data/chroma/` aufbaut – idempotent, mit
  Statistik-Ausgabe.
- Streamlit-App `src/app.py` komplett umgebaut: pro Frage
  semantische Suche, Kontext-Block, 1-Turn-Aufruf an Claude mit
  RAG-System-Prompt, Anzeige der Antwort plus ausklappbarer
  Quellenliste (mit Distanz-Anzeige).
- Test-Suite: 90 Tests grün + 3 standardmäßig übersprungene
  E2E-Tests (manuell aktivierbar mit `RUN_E2E_TESTS=1`), Laufzeit
  unter 0,7 s.

Manueller Browser-Test bestanden. RAG-System-Prompt verhindert
Halluzinationen (Negativ-Probe „Hauskatze der Alpenbank" wird
korrekt mit „keine Quelle" beantwortet).

## Welche Hindernisse gab es und wie wurden sie gelöst

- **Mehrsprachiges Embedding braucht `sentence-transformers`**: nicht
  in der Konzept-Bibliotheksliste vorgesehen. Vor Implementierung
  offengelegt, drei Optionen (mit/ohne sentence-transformers, Ollama)
  vorgelegt, Entscheidung des Nutzers eingeholt – `sentence-transformers`
  inkl. PyTorch installiert. Aufwand: ~500 MB Plattenplatz, einmaliger
  Modell-Download ~120 MB beim ersten Lauf.
- **Modell-Lade-Zeit (~70 s erstmalig, ~10 s Folge) macht Tests
  langsam**: gelöst durch Lazy-Loader `get_default_embedding_function`
  und Wrapper-Tests mit `MagicMock`-Embedding-Funktion. Echte
  Pipeline wird in zwei separat markierten E2E-Tests verifiziert,
  per Umgebungsvariable `RUN_E2E_TESTS=1` aktivierbar.
- **`from src import rag` schlug im Skript-Aufruf fehl**:
  `pytest.ini` setzt `pythonpath = .` für Tests, der direkte
  Skript-Aufruf hat den Projekt-Root nicht im Pfad. Mit
  `sys.path.insert(0, str(Path(__file__).parent.parent))` gelöst –
  pragmatisch, nicht elegant. Saubere Lösung wäre `pip install -e .`,
  für ein Lernprojekt overkill.
- **Test-Bug mit `result.lower()`**: Suchstring enthielt großes Q,
  während Vergleichsstring kleingeschrieben war – zwei Tests rot.
  Erst Ursachenanalyse (Test-Bug, kein Code-Bug), dann einzeiliger
  Fix. Bestätigt die Disziplin „erst verstehen, dann fixen".

## Welche Erkenntnisse sind für die nächsten Schritte wichtig

- **Lazy-Loading von schweren Ressourcen ist Pflicht**: das gilt
  auch für Schritt 3 (z. B. wenn wir SQLite-Connections cachen oder
  Schemata für Claude aufbereiten). Modul-Imports müssen schnell
  bleiben, sonst leiden die Tests.
- **E2E-Tests gehören per Umgebungsvariable aktivierbar gemacht**:
  `RUN_E2E_TESTS=1`-Schema funktioniert besser als hard-skip
  (`@pytest.mark.skip` ohne Bedingung wie in `test_chat.py`). Ich
  würde den vorhandenen API-Skip in `test_chat.py` rückwirkend auf
  dasselbe Schema umstellen, um Konsistenz zu schaffen.
- **Drei-Fälle-Disziplin trägt**: bei keiner Funktion fehlte später
  ein Test, weil das Pattern beim Schreiben automatisch alle
  Eingangsklassen abgedeckt hat.
- **Kleine Funktionen einzeln + Tests + Zwischenstand**: das vom
  Nutzer gewünschte Vorgehen hat sich bewährt. Pro Funktion gab es
  einen klaren Stop-Punkt, an dem Bewertung möglich war. Bei
  Schritt 3 (SQL) genauso fortsetzen.
- **Architektur-Entscheidungen früh klären**: die Diskussion
  „1-Turn vs. Multi-Turn" hätte bereits beim Vorab-Plan zu Schritt 2
  passieren können. Beim nächsten Mal solche Verhaltens-Trade-offs
  vor der Implementierung explizit auflisten.
- **Defensive Validierung an Funktions-Eingängen lohnt sich**: 
  `ValueError` mit klarer Meldung bei leeren Strings oder fehlenden
  Pflichtschlüsseln hat in mindestens drei Fällen verhindert, dass
  Folge-Funktionen kryptisch crashen. Das Pattern in Schritt 3
  beibehalten.

## Was würden wir beim nächsten Mal anders machen

- **Render-Logik gleich extrahieren**: die doppelte Quellen-Anzeige
  in `app.py` ist Code-Duplikat. Beim nächsten UI-Bau direkt eine
  `render_sources(treffer)`-Helper-Funktion ziehen.
- **`add_message` rechtzeitig anpassen oder entsorgen**: bei Schritt 4
  entscheiden, ob die Funktion weiter gebraucht wird. Toter Code
  schadet langfristig dem Vertrauen in die Test-Suite.
- **Längere Demo-Dokumente**: 5 Dokumente → 5 Chunks zeigt nicht,
  was Chunking eigentlich kann. Bei Gelegenheit zwei oder drei
  Dokumente auf 2000+ Wörter ausbauen, damit Overlap- und
  Mehrfach-Chunk-Effekte sichtbar werden.
- **Konstanten konsolidieren**: Pfade und Modell-Namen wandern aktuell
  in mehrere Dateien. Bei Schritt 3 einen zentralen Ort prüfen
  (eigene `config.py` oder bewusst in den jeweiligen Modulen halten).

## Welche offenen Punkte werden bewusst auf später verschoben

- **Multi-Turn-Konversation** mit Kontext-Tracking über mehrere
  Fragen hinweg.
- **Längere Dokumente** für sichtbares Chunking.
- **XML-Escaping** in `format_context` für Markdown-/HTML-Quellen.
- **Differenzierte Fehlerbehandlung** (Auth, Rate-Limit, Netzwerk)
  in `app.py`.
- **Test-Coverage für `app.py`** – würde eine Refaktorisierung
  (`answer_question`-Helper) voraussetzen.
- **Hybridsuche / Re-Ranking** – ausdrücklich aus dem Schritt-2-
  Scope ausgeschlossen, kommt frühestens in einer Ausbaustufe.
- **Konfigurierbares Embedding-Modell** zur Laufzeit.
- **Längen-Begrenzung des Kontexts** als Schutz gegen Token-Limits.

Diese Punkte sind im Code-Review (`docs/reviews/schritt_2_review.md`)
detaillierter aufgelistet.

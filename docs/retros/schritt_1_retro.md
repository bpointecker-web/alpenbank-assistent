# Retrospektive – Schritt 1: Einfacher Chat mit Claude

**Datum:** 2026-04-25

## Was wurde erreicht

- Projekt-Setup steht: Ordnerstruktur, virtuelle Umgebung mit Python 3.13,
  alle direkten Abhängigkeiten installiert (anthropic, chromadb, streamlit,
  python-dotenv, pytest).
- `src/chat.py` mit drei kleinen, einzeln testbaren Funktionen:
  `add_message`, `extract_response_text`, `send_to_claude`.
- 13 grüne Unit-Tests in `tests/test_chat.py`, ein bewusst übersprungener
  Integrations-Test mit echtem API-Aufruf.
- Streamlit-App `src/app.py`, die im Browser läuft, eine Nutzerfrage an
  Claude schickt und den Verlauf erhält.
- Manueller Smoke-Test im Browser bestanden: Claude antwortet, Historie
  bleibt sichtbar.

## Welche Hindernisse gab es und wie wurden sie gelöst

- **Shell-Aktivierung der Venv über `!`-Präfix funktioniert nicht.** Jeder
  `!`-Aufruf startet eine neue Bash-Shell, sodass ein vorheriges `source
  .venv/Scripts/activate` keine Wirkung mehr hat. Lösung: Streamlit direkt
  über `.venv/Scripts/python.exe -m streamlit run src/app.py` aufrufen,
  ganz ohne Aktivierung. Lehre: bei kurzlebigen Shells immer den vollen
  Venv-Pfad verwenden.
- **Konsolen-Ausgabe verstümmelt Umlaute.** Beim Smoke-Test des Imports
  erschien der System-Prompt mit `f�r` statt `für`. Ursache: cp1252-Encoding
  der Windows-Konsole. Die Datei selbst ist UTF-8. Kein echter Bug, aber
  ein Hinweis, dass Konsolen-Ausgaben unter Windows mit Vorsicht zu
  interpretieren sind.

## Welche Erkenntnisse sind für die nächsten Schritte wichtig

- **Trennung Logik/UI funktioniert und lohnt sich.** `chat.py` ohne
  Streamlit-Imports war für die Tests entscheidend. In Schritt 2 (RAG)
  sollten wir genauso vorgehen: ein `rag.py` ohne Streamlit-Bezug, in dem
  Chunking, Embedding und Suche stecken.
- **Mock-basierte Tests sind günstig und schnell.** Mit `unittest.mock` und
  `SimpleNamespace` lassen sich Anthropic-SDK-Antworten realistisch genug
  nachbauen, ohne Netzwerk und ohne API-Key. Für RAG werden wir die
  ChromaDB-Suche analog mocken können.
- **Streamlits Re-Run-Modell verstanden.** Bei jedem User-Klick läuft das
  ganze Skript erneut. Daher ist alles, was über mehrere Re-Runs hinweg
  bestehen muss, in `st.session_state` abgelegt. Das wird in Schritt 4
  wichtig, wenn Tool-Use-Aufrufe Zwischenzustände haben können.
- **Claude-API ist mit System-Prompt + messages-Liste sehr geradlinig.**
  Kein eigenes Framework nötig, kein versteckter Zustand. Das bestätigt
  die Entscheidung gegen LangChain und LlamaIndex.

## Was würden wir beim nächsten Mal anders machen

- **Gleich eine `process_turn`-Funktion einführen.** Die Komposition aus
  „User-Message anhängen → Claude rufen → Text extrahieren → Antwort
  anhängen" ist in `app.py` versteckt und unbeobachtet. In Schritt 4 mit
  Tool Use wird dieser Loop ohnehin komplexer und braucht eine eigene
  Funktion. Hätten wir das jetzt schon getan, wäre die Geschäftslogik
  bereits vollständig getestet.
- **Versions-Pinning vor dem ersten Lauf.** Ein `pip freeze >
  requirements.lock` direkt nach der ersten erfolgreichen Installation
  hätte uns Reproduzierbarkeit umsonst beschert. Holen wir vor Schritt 2
  nach, wenn der Nutzer einverstanden ist.
- **API-Key-Format validieren.** Eine kurze Prüfung „beginnt mit `sk-ant-`"
  hätte beim manuellen Test sofortiges Feedback gegeben, statt das Problem
  erst beim ersten API-Aufruf sichtbar zu machen.

## Welche offenen Punkte werden bewusst auf später verschoben

- **Streamlit-Test mit `streamlit.testing.v1.AppTest`.** Macht Sinn,
  sobald die UI mehr als triviale Logik enthält (spätestens in Schritt 4).
- **History-Begrenzung / Token-Budget.** Erst relevant, wenn längere
  Sessions oder lange RAG-Kontexte ins Spiel kommen.
- **Differenzierte API-Fehlerbehandlung** (401/429/Timeout getrennt).
  Sinnvoll, sobald die App produktiver eingesetzt würde – im Lernprojekt
  noch nicht nötig.
- **Stop-Reason auswerten.** Wichtig, sobald wir lange Antworten erwarten.
- **Datenerzeugungs-Skript** (`scripts/daten_erzeugen.py`). War nicht
  Teil von Schritt 1, ist aber Voraussetzung für Schritt 2 (RAG-Dokumente)
  und Schritt 3 (SQLite-Datenbank). Wird der erste Punkt der nächsten
  Sitzung.

## Persönliche Lerneinsicht für den Nutzer

Schritt 1 zeigt: Ein „nacktes" Chat-Interface mit der Claude-API ist
erstaunlich kurz – der Großteil der Datei `app.py` ist Boilerplate, die
eigentliche API-Interaktion sind drei Zeilen. Was Aufwand macht, ist
nicht der API-Aufruf, sondern die saubere Trennung von Logik und UI,
die testbare Strukturierung und das Nachdenken über Fehlerfälle. Genau
diese Struktur wird in den nächsten Schritten den Unterschied zwischen
„läuft halt" und „verstehe ich" ausmachen.

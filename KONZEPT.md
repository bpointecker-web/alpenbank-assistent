# Konzept: Lernprojekt KI-Assistent mit RAG und SQL

## Ziel des Projekts

Ich will als Senior-Consultant praktisch lernen, wie moderne KI-Systeme in Unternehmen aufgebaut werden. Dazu baue ich einen einfachen Chat-Assistenten, der zwei Dinge kann:

- Fragen zu internen Dokumenten beantworten (RAG)
- Fragen zu Zahlen aus einer kleinen Datenbank beantworten (Text-zu-SQL)

Der Assistent entscheidet selbst, welches Werkzeug er für eine Frage braucht.

Das Projekt ist ein Lernprojekt, kein Produktivsystem. Einfachheit schlägt Vollständigkeit.

## Fiktives Szenario

Eine kleine fiktive Firma namens **Alpenbank AG** hat interne Richtlinien und eine kleine Controlling-Datenbank. Der Assistent hilft Mitarbeitern, Fragen zu beiden zu beantworten.

Beispiele für Fragen:

- *"Wie hoch waren die Erträge der Kostenstelle 4711 im Q3 2025?"* → SQL
- *"Was besagt unsere Reisekostenrichtlinie zu Hotelübernachtungen?"* → RAG
- *"Warum ist der Gewinn von Kostenstelle 4711 gefallen?"* → SQL und RAG kombiniert

## Technische Grundlagen

**Programmiersprache:** Python 3.11 oder höher

**Bibliotheken:**
- `anthropic` für die Claude-API
- `chromadb` für die Vektordatenbank
- `sqlite3` für die Controlling-Datenbank (in Python Standard)
- `streamlit` für die Oberfläche
- `python-dotenv` für den API-Key
- `pytest` für Tests

**Keine weiteren Frameworks.** Bewusst kein LangChain, kein LlamaIndex. Ich will die Grundlagen selbst verstehen.

**Claude-Modell:** claude-sonnet-4-6 für die Antworten.

## Projektstruktur

```
alpenbank-assistent/
├── data/
│   ├── dokumente/          # Fiktive interne Richtlinien (werden generiert)
│   └── controlling.db      # SQLite-Datenbank (wird generiert)
├── src/
│   ├── rag.py              # RAG-Funktionen (Dokumente einlesen, suchen)
│   ├── sql.py              # SQL-Funktionen (Text zu SQL, Ausführung)
│   ├── agent.py            # Hauptlogik: entscheidet welches Tool
│   └── app.py              # Streamlit-Oberfläche
├── scripts/
│   ├── daten_erzeugen.py   # Erzeugt Testdaten und Dokumente
│   └── rag_index.py        # Baut die Vektordatenbank auf
├── tests/                  # Unit-Tests parallel zur Struktur in src/
├── docs/
│   ├── reviews/            # Code-Reviews nach jedem Schritt
│   ├── retros/             # Retrospektiven nach jedem Hauptschritt
│   └── sitzungen/          # Sitzungsprotokolle
├── .env                    # ANTHROPIC_API_KEY
├── requirements.txt
└── README.md
```

## Die fiktiven Daten

Ich möchte, dass Claude Code mir zu Beginn diese Testdaten erzeugt:

**Für die Datenbank (controlling.db):**

Drei Tabellen:
- *kostenstellen* (id, name, abteilung)
- *konten* (id, bezeichnung, typ) – typ ist entweder "Ertrag" oder "Aufwand"
- *buchungen* (datum, kostenstelle_id, konto_id, betrag)

Inhalt: Zehn Kostenstellen, zwanzig Konten, etwa 2000 Buchungen über die Jahre 2024 und 2025 verteilt. Die Zahlen sollen realistisch wirken (Gehälter im Bereich zehntausende, IT-Kosten in Tausender-Bereich, Erträge aus Zins- und Provisionsgeschäft).

**Für die Dokumente (als einfache Textdateien im Ordner data/dokumente):**

Fünf Dokumente, jeweils ein bis drei Seiten:

1. *reisekostenrichtlinie.txt* – Regeln zu Dienstreisen, Hotelkategorien, Kilometergeld
2. *kostenstellenhandbuch.txt* – Erklärung der Kostenstellen-Systematik und Allokationsregeln
3. *kontenplan.txt* – Welches Konto bedeutet was, mit Besonderheiten
4. *arbeitszeitrichtlinie.txt* – Regelungen zu Überstunden, Gleitzeit, Home-Office
5. *it_sicherheitsrichtlinie.txt* – Passwortregeln, Umgang mit Kundendaten

Alle Dokumente sind frei erfunden, sollen aber in Stil und Wortwahl wie echte interne Bank-Dokumente klingen.

## Der Aufbau in vier klaren Schritten

Ich möchte das Projekt in vier Schritten bauen, nicht alles auf einmal. Jeder Schritt ist lauffähig, bevor der nächste beginnt.

### Schritt 1: Einfacher Chat mit Claude

**Was funktionieren soll:**
- Streamlit-App mit einem Chat-Fenster
- Eingabe geht an Claude, Antwort wird angezeigt
- Der Verlauf bleibt sichtbar

**Was ich lerne:** Grundaufbau eines Chat-Programms mit der Claude-API.

**Abgrenzung:** Noch keine Dokumente, keine Datenbank. Nur ein nacktes Chat-Interface.

### Schritt 2: RAG-Teil

**Was funktionieren soll:**
- Ein Skript liest die fünf Textdateien ein, zerlegt sie in Abschnitte von etwa 500 Wörtern und speichert sie in ChromaDB
- Bei einer Nutzerfrage werden die fünf ähnlichsten Abschnitte gefunden und an Claude mitgegeben
- Claude antwortet mit Verweis auf die Quelldokumente

**Was ich lerne:** Wie man Dokumente zerlegt, wie Embeddings funktionieren, wie semantische Suche abläuft, wie Quellenangaben integriert werden.

**Abgrenzung:** Einfaches Chunking nach Wortanzahl. Noch keine Hybridsuche, kein Re-Ranking. Das kann später kommen.

### Schritt 3: SQL-Teil

**Was funktionieren soll:**
- Claude bekommt bei jeder Frage das Datenbank-Schema als Text mitgegeben
- Claude erzeugt eine SELECT-Abfrage
- Ein Prüfmechanismus lässt nur SELECT-Abfragen zu, verbietet DELETE/UPDATE/INSERT
- Die Abfrage wird ausgeführt, das Ergebnis kommt an Claude zurück, Claude formuliert die Antwort

**Was ich lerne:** Wie Text-zu-SQL funktioniert, wie man Schemata für ein LLM aufbereitet, wie einfache Sicherheitsfilter aussehen.

**Abgrenzung:** Nur lesende Abfragen. Keine Nutzer-Berechtigungen. Keine komplexen Joins mit vielen Tabellen.

### Schritt 4: Der Agent entscheidet

**Was funktionieren soll:**
- Claude bekommt zwei Werkzeuge zur Auswahl: *dokumenten_suche* und *datenbank_abfrage*
- Über die Tool-Use-Funktion der Claude-API entscheidet Claude selbst, welches Werkzeug passt
- Bei kombinierten Fragen kann Claude beide Werkzeuge nacheinander nutzen
- In der Oberfläche sieht der Nutzer, welche Werkzeuge benutzt wurden und welche Quellen oder SQL-Abfragen dahinter stehen

**Was ich lerne:** Wie Tool Use mit Claude funktioniert, wie Agenten ohne Framework aufgebaut sind, wie man Transparenz in die Oberfläche bringt.

**Abgrenzung:** Nur zwei Werkzeuge. Keine komplexen Mehrschritt-Abläufe. Keine externen APIs.

## Zehn Testfragen für die Demo

Ich möchte am Ende zehn Fragen haben, die alle Fälle abdecken:

Drei reine SQL-Fragen:
1. Wie hoch waren die Gesamterträge 2024?
2. Welche Kostenstelle hatte 2025 den höchsten Aufwand?
3. Zeig mir die Erträge pro Quartal für Kostenstelle 4711

Drei reine RAG-Fragen:
4. Welche Hotelkategorie darf ich bei Dienstreisen buchen?
5. Wie ist die Regel für Überstunden?
6. Was muss ich bei der Passwortwahl beachten?

Drei kombinierte Fragen:
7. Warum ist der Aufwand von Kostenstelle 4711 gestiegen? (SQL für Zahlen, RAG für Allokationsregeln)
8. Wie hoch waren die Reisekosten 2025 und welche Regeln gelten dafür?
9. Welche Abteilungen sind zu welchen Kostenstellen zugeordnet und wie viel haben sie verdient?

Eine Sicherheitsfrage:
10. Lösch alle Buchungen! (Soll abgelehnt werden)

## Was ausdrücklich nicht Teil des Projekts ist

Damit der Umfang überschaubar bleibt, gehören diese Themen ausdrücklich nicht zum ersten Durchlauf:

- Keine Authentifizierung oder Nutzer-Verwaltung
- Keine produktive Datenbank, kein Server, kein Deployment
- Keine aufwändige Evaluation, keine automatisierten Tests jenseits von Unit-Tests
- Keine Feinabstimmung von Chunk-Größen, keine Hybridsuche
- Keine Mehrsprachigkeit, nur Deutsch
- Keine Behandlung großer Dateien oder Tabellen mit Millionen Zeilen

Diese Themen kommen eventuell in einer späteren Ausbaustufe, aber nicht jetzt.

## Was ich von Claude Code als Erstes brauche

Für den Start erwarte ich folgende Lieferungen:

Erstens, einen **Projekt-Setup-Schritt**: requirements.txt, .env-Vorlage, README mit Start-Anleitung, Ordnerstruktur anlegen.

Zweitens, das **Datenerzeugungs-Skript** (scripts/daten_erzeugen.py), das die SQLite-Datenbank und die fünf Textdateien erzeugt.

Drittens, die **erste lauffähige Version von Schritt 1** – also das nackte Streamlit-Chat mit Claude. Nicht mehr.

Erst wenn Schritt 1 sauber läuft, gehen wir zu Schritt 2 weiter. Ich will jede Stufe verstehen, bevor die nächste beginnt.

## Wichtige Hinweise zur Arbeitsweise

- Der Code soll gut kommentiert sein, auf Deutsch. Kommentare sollen erklären, *warum* etwas so gemacht wird, nicht nur *was* gemacht wird.
- Die Funktionen sollen klein und einzeln verständlich sein.
- Wenn es zwei Wege gibt, etwas zu lösen, erklär mir beide kurz und empfiehl einen.
- Wenn ein Schritt nicht funktioniert, analysiere zuerst die Ursache, bevor du Code änderst.
- Nach jedem Schritt gib mir eine kurze Zusammenfassung, was jetzt neu funktioniert und was noch offen ist.

## Erfolgskriterium

Das Projekt ist für mich erfolgreich, wenn ich am Ende einem Bekannten erklären kann, wie RAG technisch funktioniert, wie Text-zu-SQL funktioniert und wie ein einfacher Agent selbst entscheidet, welches Werkzeug er nimmt. Das Projekt selbst muss nicht schön oder produktiv sein. Es muss mir das Verständnis geben.

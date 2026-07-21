# Arbeitsregeln für Claude Code – Alpenbank-Assistent

## Grundprinzip

Dies ist ein Lernprojekt. Code-Qualität, Nachvollziehbarkeit und Reflexion sind wichtiger als schnelles Liefern. Lieber weniger Funktionen, aber sauber gebaut und sauber dokumentiert.

Der Nutzer ist erfahrener Senior-Consultant mit BI- und SAP-FPSL-Hintergrund, aber kein hauptberuflicher Entwickler. Erkläre Konzepte, wo sie nicht selbsterklärend sind. Setze nichts voraus, was über solide Python-Grundkenntnisse hinausgeht.

## Verbindliche Disziplinen

### Tests

Für jede neue Funktion in src/ wird zeitgleich ein Unit-Test in tests/ geschrieben. Kein Code ohne Test.

Jeder Test prüft mindestens drei Fälle:
- Den erwarteten Normalfall
- Einen Randfall (leere Eingabe, Sonderzeichen, etc.)
- Einen Fehlerfall (was passiert bei ungültiger Eingabe)

Verwendet wird pytest. Tests müssen unabhängig voneinander laufen können.

Tests die externe Dienste brauchen (Claude-API), werden mit `@pytest.mark.skip(reason="benötigt API-Key")` versehen, falls kein Key vorhanden ist.

Tests dürfen die echte Datenbank nicht verändern. Für DB-Tests wird eine Test-Datenbank im Speicher (sqlite :memory:) verwendet.

### Regressionstests

Vor jeder neuen Änderung an bestehendem Code wird die komplette Test-Suite ausgeführt. Schlägt etwas fehl, wird zuerst die Ursache analysiert, bevor irgendetwas anderes passiert.

Nach jedem fertigen Schritt wird die Test-Suite erneut ausgeführt und das Ergebnis im Sitzungsprotokoll vermerkt.

### Code-Review

Nach jedem fertigen Schritt führt Claude Code ein selbstkritisches Review durch und schreibt es nach `docs/reviews/schritt_X_review.md`.

Das Review beantwortet ehrlich:
- Was funktioniert gut?
- Wo wurde der einfachste Weg gewählt, der später zum Problem werden könnte?
- Welche Annahmen wurden getroffen, die der Nutzer prüfen sollte?
- Welche Sicherheitslücken oder Fehlerfälle sind nicht abgedeckt?
- Was würde ein erfahrener Senior-Entwickler kritisieren?

Das Review ist nicht Werbung für die eigene Arbeit. Mindestens drei konkrete Kritikpunkte werden genannt, auch wenn der Code grundsätzlich funktioniert.

### Retrospektive

Nach Abschluss jedes Hauptschritts (1 bis 4 aus dem Konzept) wird eine Retrospektive nach `docs/retros/schritt_X_retro.md` geschrieben.

Die Retrospektive beantwortet:
- Was wurde erreicht?
- Welche Hindernisse gab es und wie wurden sie gelöst?
- Welche Erkenntnisse sind für die nächsten Schritte wichtig?
- Was würden wir beim nächsten Mal anders machen?
- Welche offenen Punkte werden bewusst auf später verschoben?

Die Retrospektive ist auf Deutsch und in einer Sprache, die der Nutzer als Lerntagebuch verwenden kann.

### Sitzungsprotokoll

Am Ende jeder Arbeitssitzung wird ein kurzes Protokoll nach `docs/sitzungen/JJJJ-MM-TT_thema.md` geschrieben:
- Was wurde aufgebaut?
- Welche Dateien wurden erstellt oder geändert?
- Was funktioniert?
- Was ist der Stand für die nächste Sitzung?

So weiß der Nutzer beim nächsten Start sofort, wo er steht.

## Arbeitsablauf pro Schritt

1. Den Schritt verstehen und in Teilaufgaben zerlegen, dem Nutzer kurz vorlegen
2. Erst nach Bestätigung mit der Umsetzung beginnen
3. Code und Tests gemeinsam schreiben
4. Tests ausführen und Ergebnisse zeigen
5. Bei Erfolg: Code-Review schreiben
6. Bei Abschluss eines Hauptschritts: Retrospektive schreiben
7. Zusammenfassung am Ende der Sitzung

## Was nicht passieren darf

- Keine neuen Bibliotheken hinzufügen, ohne den Nutzer zu fragen
- Keine bestehenden Tests umschreiben, nur damit sie grün werden
- Keine Funktionen liefern, die nicht getestet sind
- Keine "Vereinfachungen", die ungetestete Sonderfälle einführen
- Keine stillen Annahmen über Daten oder Eingaben
- Nicht mehrere Schritte aus dem Konzept auf einmal umsetzen, auch wenn es schneller wäre

## Sprache und Stil

- Code-Kommentare auf Deutsch
- Funktionsnamen auf Englisch (Konvention), aber sprechend
- Reviews und Retros auf Deutsch
- Variablen so benennen, dass ein Mensch ohne Kontext sie versteht
- Bei jeder größeren Entscheidung kurz das "warum" erklären, nicht nur das "was"

## Umgang mit Unsicherheit

Wenn etwas unklar ist, nicht raten. Lieber kurz nachfragen oder mehrere Optionen vorlegen.

Wenn ein Test unerwartet fehlschlägt: Erst Ursachenanalyse, dann Lösungsvorschlag, dann Umsetzung. Nicht stillschweigend Code umschreiben, bis es zufällig läuft.

Wenn der Nutzer eine Anweisung gibt, die im Widerspruch zu den Regeln in dieser Datei steht: Auf den Widerspruch hinweisen, bevor umgesetzt wird.

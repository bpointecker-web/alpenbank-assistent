# Projekt-Zusammenfassung: KI-Assistent für die Alpenbank AG

Stand: 2026-04-29 (Schritte 1–4 abgeschlossen)

Diese Zusammenfassung beschreibt das Projekt auf der Ebene, auf der es
einem Senior Business Analyst erklärt würde – ohne Code, ohne
Implementierungsdetails, mit Fokus auf Architektur, Vorgehen und
Erkenntnissen. Detail-Dokumentation siehe `KONZEPT.md`, die
Sitzungsprotokolle und die Code-Reviews in `docs/`.

## Ausgangslage und Ziel

Wir haben einen Chat-Assistenten gebaut, der Fragen von Mitarbeitern
einer fiktiven Bank beantwortet – und das aus zwei sehr
unterschiedlichen Wissensquellen: **internen Dokumenten**
(Reisekostenrichtlinie, IT-Sicherheit, Arbeitszeit etc.) und einer
**Controlling-Datenbank** (Buchungen, Kostenstellen, Konten). Das
Besondere: der Assistent entscheidet selbst, welche Quelle er für eine
Frage anzapft. Bei kombinierten Fragen kombiniert er beide.

Das Projekt war als **Lernprojekt** gerahmt, nicht als Produkt.
Lernziel: einmal von innen verstehen, wie moderne KI-Architekturen mit
RAG, Text-zu-SQL und Tool-Use-Agenten konkret zusammenspielen – ohne
hinter Frameworks wie LangChain zu verschwinden.

## Wie die Lösung aufgebaut ist

Drei zentrale Bausteine arbeiten zusammen:

**Erstens, semantische Dokumentensuche (RAG).** Die Richtlinien-Texte
werden in Abschnitte zerlegt, jeder Abschnitt wird in einen
mathematischen Vektor übersetzt (Embedding) und in einer
Vektordatenbank abgelegt. Bei einer Frage wird der ähnlichste
Abschnitt gesucht und an Claude mitgegeben – Claude antwortet
ausschließlich auf Basis dieses Kontexts und nennt die Quelle. Das
verhindert Halluzinationen.

**Zweitens, Text-zu-SQL.** Claude bekommt das Datenbankschema
beschrieben und erzeugt aus einer Frage in natürlicher Sprache ein
SELECT-Statement. Bevor es ausgeführt wird, prüft eine **Whitelist**,
dass es wirklich nur ein lesendes Statement ist – DELETE, UPDATE,
INSERT werden geblockt. Zusätzlich öffnen wir die Datenbank im
Read-Only-Modus, und der System-Prompt verbietet schreibende Befehle
ausdrücklich. Dreifacher Schutz für eine Lerndemo wirkt übertrieben,
aber genau dieses „Defense in Depth" macht das Sicherheitskonzept
didaktisch greifbar.

**Drittens, der Agent mit Tool Use.** Claude bekommt die zwei
Werkzeuge (Dokumentensuche und Datenbankabfrage) als formal definierte
Tools angeboten und entscheidet pro Frage selbst, welches er ruft. Bei
Fragen wie *„Warum ist der Aufwand von Kostenstelle 4711 gestiegen?"*
nutzt er beide nacheinander – erst die Datenbank für die Zahlen, dann
die Dokumente für die Allokationsregeln, und kombiniert beide
Erkenntnisse zu einer Antwort. Eine Schleife im Code begleitet diesen
Prozess: Claude sagt „ich brauche Werkzeug X mit Eingabe Y", der Code
führt aus, schickt das Ergebnis zurück, Claude entscheidet erneut –
bis die Antwort steht oder ein Iterationslimit greift.

Über allem liegt ein einfaches Streamlit-Chat-Interface, das pro
Antwort transparent zeigt, welche Werkzeuge Claude eingesetzt hat –
damit der Nutzer den Weg zur Antwort nachvollziehen kann.

## Wie wir vorgegangen sind

Der Aufbau erfolgte in **vier expliziten Stufen**, nicht in einem
großen Wurf. Jede Stufe war für sich lauffähig, bevor die nächste
begann:

1. Nacktes Streamlit-Chat mit Claude (Grundgerüst)
2. RAG ergänzt (Dokumentensuche aktiv)
3. Text-zu-SQL ergänzt (Datenbankabfragen aktiv, mit Modus-Schalter)
4. Tool-Use-Agent (Modus-Schalter ersetzt durch selbstentscheidenden
   Claude)

Diese Disziplin – „erst Stufe X läuft, dann Stufe X+1" – hat sich als
das wertvollste Strukturprinzip erwiesen. Jede Stufe wurde mit
Code-Review, Retrospektive und Sitzungsprotokoll abgeschlossen.

Eine Methodik aus Stufe 3, die sich in Stufe 4 dramatisch ausgezahlt
hat: **Architektur-Vorab-Klärung**. Bevor irgendein Code geschrieben
wurde, haben wir fünf konkrete Detail-Entscheidungen schriftlich
festgelegt (Tool-Vertrag, Schema-Lokalität, Iterationslimit,
Fehler-Handling, Modul-Struktur). Während der Implementierung musste
keine einzige Entscheidung revidiert werden. Die zehn Minuten
Vor-Diskussion haben Stunden Refactoring gespart.

## Was hat sich technisch bewährt

- **Trennung der Schichten** – die reine Logik (Suche, SQL, Agent) ist
  von der UI vollständig entkoppelt und ohne Browser testbar
- **Mock-basierte Tests** des Agent-Loops – kein echter API-Aufruf
  nötig, um zu verifizieren, dass die Multi-Turn-Schleife korrekt mit
  Tool-Aufrufen, Fehlern und Iterationslimits umgeht
- **Drei Verifikations-Stufen** vor jeder „fertig"-Meldung:
  automatisierte Unit-Tests, programmatischer Skript-Durchlauf,
  manueller Browser-Test mit allen zehn Demo-Fragen
- **Konsequente Defensive bei Sicherheit** – die SQL-Whitelist, die
  Read-Only-Verbindung und die System-Prompt-Regel arbeiten unabhängig
  voneinander, jede Schicht würde alleine den Schreibversuch blockieren

## Was bewusst nicht im Scope war

Authentifizierung, Mehrbenutzerbetrieb, Audit-Logs,
Token-Budget-Limitierung, Streaming-Antworten, Mehrsprachigkeit. Das
sind alles Themen, die ein Produkt-System bräuchte – ein Lernprojekt
nicht. Wer das Projekt produktivieren wollte, hätte hier die nächsten
Stationen.

## Erfolgskriterium erreicht

Das selbstgesetzte Erfolgskriterium war: *„am Ende einem Bekannten
erklären können, wie RAG funktioniert, wie Text-zu-SQL funktioniert
und wie ein einfacher Agent selbst entscheidet, welches Werkzeug er
nimmt."* Genau das ist passiert. Der Code ist klein genug, um an einem
Nachmittag durchgelesen zu werden, und groß genug, um die Konzepte
realistisch abzubilden.

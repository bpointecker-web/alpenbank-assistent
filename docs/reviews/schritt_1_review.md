# Code-Review – Schritt 1: Einfacher Chat mit Claude

**Datum:** 2026-04-25
**Reviewer:** Claude Code (selbstkritisch, gemäß CLAUDE.md)

## Was funktioniert gut

- **Klare Trennung von Logik und UI.** `src/chat.py` enthält keine
  Streamlit-Aufrufe und ist dadurch ohne UI-Framework testbar. `src/app.py`
  enthält keine API-Aufrufe direkt, sondern delegiert an `chat.py`. Diese
  Trennung wird sich in Schritt 2 und 3 auszahlen, wenn weitere Werkzeuge
  hinzukommen.
- **Immutability bei `add_message`.** Die Funktion mutiert die übergebene
  Historie nicht. Das passt zum Re-Run-Modell von Streamlit und erleichtert
  Tests.
- **Drei kleine Funktionen statt einer großen.** `add_message`,
  `extract_response_text` und `send_to_claude` sind jeweils einzeln testbar.
  Vor allem die Trennung „API-Aufruf" und „Antwort parsen" hat sich bewährt:
  in den Unit-Tests konnten beide Teile mit minimalen Mocks geprüft werden.
- **Tests decken Normalfall, Randfälle und Fehlerfälle ab.** 13 grüne Tests
  bei 3 produktiven Funktionen ist eine ehrliche Quote, kein Alibi.

## Wo der einfachste Weg gewählt wurde – und das später Probleme machen kann

### 1. Die UI-Schleife in `app.py` ist nicht gekapselt und damit nicht getestet

Der Block in `app.py`, der eine Nutzereingabe verarbeitet (User-Message
anhängen → Claude rufen → Antwort extrahieren → Antwort anhängen → Historie
aktualisieren), liegt direkt im Streamlit-Skript-Body. Eine Funktion wie
`process_turn(client, history, user_text) -> tuple[list, str]` würde diesen
Ablauf testbar und wiederverwendbar machen. Spätestens wenn in Schritt 4
der Tool-Use-Loop dazu kommt (der mehrere API-Aufrufe pro Turn macht), wird
das nachgezogen werden müssen. **Bewusst nicht jetzt gebaut**, um den Plan
nicht zu erweitern – aber ein klarer Verbesserungspunkt für die nächste
Iteration.

### 2. Pauschales `except Exception` in `app.py`

Wir fangen jeden Fehler aus der Anthropic-SDK gleich behandelt – ob Auth,
Rate-Limit, Timeout oder Schema-Bruch. Für ein Lernprojekt akzeptabel, aber
in einem echten System wäre eine Differenzierung Pflicht: ein 401 verlangt
andere Reaktion als ein 429 oder ein Netzwerk-Timeout. Aktuell sieht der
Nutzer nur „Fehler beim Aufruf der Claude-API: …" und muss aus der Meldung
selbst raten. Auch die Stack-Trace bleibt unsichtbar.

### 3. Keine Längenbegrenzung der Historie

Bei jeder neuen Eingabe wird die komplette Historie an Claude geschickt.
Die Token-Kosten wachsen damit quadratisch zur Sitzungsdauer, und ab einem
gewissen Punkt schlägt das Kontextfenster zu. Es gibt aktuell keinen
Mechanismus für Trimming, Zusammenfassung oder ein Hard-Limit. Für die
Demo unkritisch, für längere Sessions kostenrelevant. **Annahme, die der
Nutzer prüfen sollte:** ist die Demo immer kurz, oder soll später ein
Mechanismus rein?

### 4. `MAX_TOKENS = 1024` als globale Konstante

Der Wert ist nicht pro Aufruf überschreibbar. Für Schritt 1 reicht das.
Sobald in Schritt 3 SQL-Antworten oder in Schritt 2 lange RAG-Antworten
kommen, brauchen wir vermutlich mehr Spielraum. Sollte als Parameter von
`send_to_claude` zugänglich gemacht werden, sobald der Bedarf konkret ist.

## Welche Sicherheitslücken oder Fehlerfälle sind nicht abgedeckt

- **Stop-Reason wird ignoriert.** Wenn Claude wegen MAX_TOKENS abbricht,
  bekommt der Nutzer eine abgeschnittene Antwort, ohne dass das im UI
  signalisiert wird. Sollte später `response.stop_reason` ausgewertet werden.
- **Kein Schutz gegen leere oder absurd lange User-Eingaben.** `st.chat_input`
  liefert beliebige Strings; Validierung passiert nur auf „komplett leer"
  in `add_message`. Eingaben mit 100.000 Zeichen würden ungebremst an die
  API geschickt.
- **Kein Schutz gegen API-Kosten.** Es gibt weder einen Anfrage-Counter
  noch ein Tageslimit. Eine versehentlich offen gelassene App mit langem
  Verlauf könnte unbemerkt Kosten produzieren.
- **`requirements.txt` ohne Versions-Pinning.** Reproduzierbare Builds sind
  nicht garantiert. Für ein Lernprojekt vertretbar, ein `pip freeze >
  requirements.lock` wäre aber günstig vor der nächsten Sitzung.

## Was würde ein erfahrener Senior-Entwickler kritisieren

- **Streamlit-Skript nicht durch automatisierten Test abgedeckt.** Es gäbe
  das `streamlit.testing.v1.AppTest`-Framework, das wir nicht eingesetzt
  haben. Damit könnte zumindest geprüft werden, dass die Initialisierung
  durchläuft, der Fehlerpfad bei fehlendem API-Key sauber abbricht und
  ein simulierter User-Input die Historie korrekt fortschreibt. Wäre kein
  großer Aufwand und würde die UI-Schicht aus der reinen Sichtprüfung
  herausholen.
- **`extract_response_text` schluckt nicht-Text-Blöcke kommentarlos.** Im
  aktuellen Schritt unkritisch, in Schritt 4 (Tool Use) müsste das bewusst
  überarbeitet werden – sonst gehen Tool-Use-Aufrufe in Stille verloren.
- **API-Key-Handhabung minimal.** `.env` ist Standard, aber es gibt keine
  Validierung des Key-Formats und keinen Hinweis, wenn der Key syntaktisch
  unsinnig aussieht. Das schlägt erst beim ersten echten API-Aufruf auf.

## Fazit

Schritt 1 erfüllt das Konzept-Ziel: ein lauffähiges, klar strukturiertes
Chat-Interface mit verstehbarer Logik. Die offenen Punkte sind benannt und
bewusst auf später verschoben. Mit der gleichen Disziplin können wir
Schritt 2 (RAG) angehen, ohne uns selbst zu belügen.

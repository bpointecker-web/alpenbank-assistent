"""Daten-Erzeugung für den Alpenbank-Assistenten.

Erzeugt:
  * eine SQLite-Datenbank ``data/controlling.db`` mit drei Tabellen
    (kostenstellen, konten, buchungen) und ca. 2000 fiktiven Buchungen
  * fünf fiktive interne Richtlinien als Textdateien unter
    ``data/dokumente/``

Das Skript ist deterministisch: derselbe Seed liefert bei jedem Lauf
identische Daten. Wiederholtes Ausführen löscht und ersetzt die
Datenbank, damit kein "schiefer" Zustand aus früheren Läufen entsteht.

Aufruf aus dem Projekt-Root:
    .venv/Scripts/python.exe scripts/daten_erzeugen.py
"""

from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Konstanten
# ---------------------------------------------------------------------------

# Fester Seed sichert Reproduzierbarkeit. Wer wirklich Variation will,
# kann seed_database() mit einem anderen Wert aufrufen.
SEED = 42

# Pfade relativ zum Projekt-Root. Aufruf des Skripts erwartet, dass das
# aktuelle Arbeitsverzeichnis das Projekt-Root ist.
DB_PATH = Path("data/controlling.db")
DOC_DIR = Path("data/dokumente")

# Buchungszeitraum: zwei volle Geschäftsjahre, wie im Konzept verlangt.
START_DATUM = date(2024, 1, 1)
END_DATUM = date(2025, 12, 31)

# Anzahl der zu erzeugenden Buchungen. ~2000 verteilt auf 731 Tage ergibt
# durchschnittlich knapp drei Buchungen pro Tag – realistisch klein für
# eine fiktive kleine Bank.
ANZAHL_BUCHUNGEN = 2000

# ---------------------------------------------------------------------------
# Stammdaten: Kostenstellen
# ---------------------------------------------------------------------------
# Format: (id, name, abteilung)
# Nummern-Logik laut Kostenstellenhandbuch:
#   4xxx Vertrieb, 5xxx IT/Service, 6xxx Stab, 7xxx übergreifend.
# So passen Stammdaten und Doku-Inhalte zusammen.
KOSTENSTELLEN: list[tuple[int, str, str]] = [
    (4711, "Privatkundengeschäft Wien", "Vertrieb"),
    (4712, "Privatkundengeschäft Salzburg", "Vertrieb"),
    (4801, "Firmenkundengeschäft", "Vertrieb"),
    (4901, "Treasury", "Handel"),
    (5101, "IT-Infrastruktur", "IT"),
    (5102, "IT-Anwendungen", "IT"),
    (6001, "Personalwesen", "Stab"),
    (6101, "Risikomanagement", "Stab"),
    (6201, "Compliance", "Stab"),
    (7001, "Filialnetz Allgemein", "Vertrieb"),
]

# ---------------------------------------------------------------------------
# Stammdaten: Konten
# ---------------------------------------------------------------------------
# Format: (id, bezeichnung, typ)
# typ ist "Ertrag" (4xxx) oder "Aufwand" (6xxx) – siehe kontenplan.txt.
KONTEN: list[tuple[int, str, str]] = [
    # Erträge
    (4000, "Zinserträge Kreditgeschäft", "Ertrag"),
    (4010, "Zinserträge Wertpapiere", "Ertrag"),
    (4100, "Provisionserträge Wertpapiere", "Ertrag"),
    (4110, "Provisionserträge Zahlungsverkehr", "Ertrag"),
    (4200, "Provisionserträge Bauspar", "Ertrag"),
    (4300, "Handelsergebnis Devisen", "Ertrag"),
    (4400, "Sonstige betriebliche Erträge", "Ertrag"),
    (4500, "Auflösung Risikovorsorge", "Ertrag"),
    # Aufwendungen
    (6000, "Personalaufwand Gehälter", "Aufwand"),
    (6010, "Personalaufwand Sozialabgaben", "Aufwand"),
    (6020, "Personalaufwand Boni", "Aufwand"),
    (6100, "Raumkosten Miete", "Aufwand"),
    (6110, "Raumkosten Nebenkosten", "Aufwand"),
    (6200, "IT-Kosten Hardware", "Aufwand"),
    (6210, "IT-Kosten Software-Lizenzen", "Aufwand"),
    (6220, "IT-Kosten Wartung", "Aufwand"),
    (6300, "Reisekosten", "Aufwand"),
    (6400, "Beratungskosten", "Aufwand"),
    (6500, "Marketing", "Aufwand"),
    (6600, "Risikovorsorge Kreditgeschäft", "Aufwand"),
]

# ---------------------------------------------------------------------------
# Dokumente
# ---------------------------------------------------------------------------
# Inline gehalten (Option 1 aus der Planung): ein Skript, alles an einem Ort.
# Sprache und Wortwahl orientieren sich an typischen internen Bank-Texten.

DOKUMENTE: dict[str, str] = {
    "reisekostenrichtlinie.txt": """Reisekostenrichtlinie der Alpenbank AG

Stand: Januar 2024
Gültig für alle Mitarbeiterinnen und Mitarbeiter der Alpenbank AG

1. Geltungsbereich

Diese Richtlinie regelt die Erstattung von Reisekosten bei dienstlich
veranlassten Reisen. Sie gilt für alle Beschäftigten der Alpenbank AG sowie
für freie Mitarbeiter, sofern dies vertraglich vereinbart wurde.

2. Genehmigung von Dienstreisen

Jede Dienstreise bedarf der vorherigen Genehmigung durch die unmittelbare
Führungskraft. Reisen ins Ausland sind zusätzlich vom Bereichsleiter zu
genehmigen. Die Genehmigung erfolgt im internen Reisebuchungssystem
spätestens fünf Werktage vor Reiseantritt.

3. Hotelkategorien

Bei Übernachtungen sind ausschließlich Hotels der Kategorien drei oder vier
Sterne zu wählen. Hotels der Kategorie fünf Sterne sind nur in begründeten
Ausnahmefällen und nach Freigabe durch den Vorstand zulässig.

Maximale Übernachtungskosten je Person und Nacht:
- Inland: 150 Euro
- Europäisches Ausland: 200 Euro
- Außereuropäisches Ausland: 250 Euro

In Wien, München, Zürich und Frankfurt gilt ein Aufschlag von 30 Prozent.

4. Verpflegungsmehraufwand

Die steuerlich anerkannten Pauschalen für Verpflegungsmehraufwand werden
übernommen. Bei Bewirtung durch den Arbeitgeber oder Geschäftspartner
reduziert sich die Pauschale entsprechend.

5. Fahrtkosten

Bei Nutzung des privaten Kraftfahrzeugs wird ein Kilometergeld in Höhe von
0,42 Euro je gefahrenem Kilometer erstattet. Mitfahrer aus dem Unternehmen
erhalten einen Aufschlag von 0,05 Euro je Kilometer.

Bei Bahnreisen ist grundsätzlich die zweite Klasse zu nutzen. Reisen erster
Klasse sind nur bei Reisedauer über vier Stunden oder bei zwingenden
arbeitsbezogenen Gründen erlaubt.

Flüge sind in der Economy Class zu buchen. Business Class ist bei Flugzeit
über sechs Stunden oder bei direkt anschließenden Geschäftsterminen zulässig.

6. Abrechnung

Reisekosten sind innerhalb von zwei Wochen nach Reiseende über das interne
Reisebuchungssystem abzurechnen. Originalbelege sind beizufügen oder digital
hochzuladen. Verspätete Abrechnungen können nach drei Monaten nicht mehr
berücksichtigt werden.

7. Sonderregelungen

Für mehrtägige Reisen mit Wochenend-Überbrückung gilt eine
Pauschalvergütung. Details hierzu sind beim Personalbereich zu erfragen.
""",

    "kostenstellenhandbuch.txt": """Kostenstellenhandbuch der Alpenbank AG

Stand: März 2024
Verantwortlich: Bereich Controlling

1. Zweck dieses Handbuchs

Das Kostenstellenhandbuch beschreibt die Systematik der
Kostenstellenrechnung in der Alpenbank AG. Es dient als verbindliche
Grundlage für die Zuordnung von Aufwendungen und Erträgen sowie für die
monatliche Auswertung.

2. Aufbau der Kostenstellennummern

Die Kostenstellennummer ist vierstellig und folgt einer festen Logik:
- 4xxx: Vertriebskostenstellen (Privat- und Firmenkundengeschäft)
- 5xxx: Service- und Infrastrukturkostenstellen, insbesondere IT
- 6xxx: Stabskostenstellen (Personal, Risiko, Compliance)
- 7xxx: Allgemeine und übergreifende Kostenstellen

Innerhalb jeder Hauptgruppe werden Untergliederungen nach Region oder
fachlicher Zuständigkeit vorgenommen.

3. Verantwortlichkeiten

Jede Kostenstelle hat einen benannten Kostenstellenverantwortlichen, in der
Regel die fachliche Führungskraft. Diese Person ist für die korrekte
Buchung von Aufwendungen, die Plausibilität der Kostenstellenauswertung
sowie die Abweichungsanalyse zum Plan verantwortlich.

4. Allokationsregeln

Direkte Kosten werden unmittelbar der verursachenden Kostenstelle belastet.
Beispiele:
- Gehälter: Kostenstelle des Mitarbeiters laut Personalstammdaten
- Reisekosten: Kostenstelle des reisenden Mitarbeiters
- IT-Hardware: Kostenstelle des Empfängers, sofern eindeutig zuordenbar

Gemeinkosten werden nach festgelegten Verteilungsschlüsseln umgelegt:
- Gebäude- und Raumkosten: nach genutzter Fläche in Quadratmetern
- IT-Grundinfrastruktur: nach Anzahl der vergebenen Arbeitsplätze
- Personalbereich: nach Anzahl der zugeordneten Mitarbeiter
- Vorstandsbüro und Aufsichtsrat: gleichmäßig auf alle Vertriebskostenstellen

5. Innerbetriebliche Leistungsverrechnung

Servicebereiche, insbesondere die IT-Bereiche und das Personalwesen,
verrechnen ihre Leistungen quartalsweise an die empfangenden
Kostenstellen. Die Verrechnungssätze werden jährlich vom Bereich
Controlling neu ermittelt und in der Ergebnisrechnung dokumentiert.

6. Plan-Ist-Vergleich

Jede Kostenstelle erhält monatlich eine Auswertung mit Plan-, Ist- und
Vorjahreswerten. Abweichungen größer als zehn Prozent oder zwanzigtausend
Euro pro Monat sind durch den Kostenstellenverantwortlichen zu kommentieren.

7. Änderungen an Kostenstellen

Neue Kostenstellen werden ausschließlich vom Bereich Controlling angelegt.
Änderungen an bestehenden Kostenstellen, etwa Umbenennungen oder
Abteilungswechsel, sind schriftlich beim Controlling zu beantragen und mit
ausreichender Vorlaufzeit vor Monatsabschluss durchzuführen.
""",

    "kontenplan.txt": """Kontenplan und Buchungssystematik der Alpenbank AG

Stand: Januar 2024
Verantwortlich: Bereich Rechnungswesen

1. Einleitung

Dieser Kontenplan beschreibt die in der Ergebnisrechnung verwendeten
Sachkonten. Er ist abgeleitet aus dem Bankenkontenrahmen und an die
internen Steuerungsanforderungen der Alpenbank AG angepasst.

2. Aufbau der Kontonummern

Die Kontonummern sind vierstellig. Die erste Ziffer kennzeichnet die
Konten-Hauptgruppe:
- 4xxx: Erträge aus dem operativen Bankgeschäft
- 5xxx: Außerordentliche und sonstige Erträge (derzeit nicht in Verwendung)
- 6xxx: Aufwendungen aller Art

Innerhalb der Hauptgruppen erfolgt die weitere Gliederung nach
Geschäftsfeld oder Aufwandsart.

3. Wichtige Ertragskonten

- 4000 Zinserträge Kreditgeschäft: Erträge aus an Kunden vergebenen
  Krediten, einschließlich Bauspar- und Hypothekendarlehen
- 4010 Zinserträge Wertpapiere: Erträge aus dem Wertpapierbestand der
  Bank, insbesondere Anleihen
- 4100 Provisionserträge Wertpapiere: Provisionen aus
  Wertpapierdienstleistungen für Kunden
- 4110 Provisionserträge Zahlungsverkehr: Gebühren aus dem laufenden
  Zahlungsverkehr
- 4500 Auflösung Risikovorsorge: Auflösung von Wertberichtigungen, wenn
  sich Risiken nicht realisieren

4. Wichtige Aufwandskonten

- 6000 Personalaufwand Gehälter: Bruttogehälter aller fest angestellten
  Mitarbeiter
- 6010 Personalaufwand Sozialabgaben: Arbeitgeberanteile zur
  Sozialversicherung
- 6020 Personalaufwand Boni: Variable Vergütungsbestandteile
- 6100 bis 6110 Raumkosten: Mieten und Nebenkosten der Gebäude
- 6200 bis 6220 IT-Kosten: Hardware, Software-Lizenzen, Wartung
- 6300 Reisekosten: gemäß Reisekostenrichtlinie
- 6600 Risikovorsorge Kreditgeschäft: Wertberichtigungen auf gefährdete
  Kreditforderungen

5. Besonderheiten

Die Konten 6020 (Boni) und 6600 (Risikovorsorge) weisen typischerweise
starke saisonale Schwankungen auf und konzentrieren sich auf das vierte
Quartal des Geschäftsjahres. Bei Auswertungen ist dies zu berücksichtigen.

Das Konto 4500 (Auflösung Risikovorsorge) ist ein Ertragskonto, obwohl es
inhaltlich eine Korrektur einer früheren Aufwandsbuchung darstellt. In der
internen Ergebnisrechnung wird es saldiert mit Konto 6600 dargestellt.

6. Buchungslogik

Alle Beträge werden grundsätzlich mit positivem Vorzeichen gebucht. Die
Unterscheidung zwischen Ertrag und Aufwand erfolgt über das Feld typ in
der Tabelle der Sachkonten. Für die Berechnung von Salden und
Deckungsbeiträgen werden Aufwendungen rechentechnisch invertiert.

7. Anlage neuer Konten

Neue Sachkonten werden ausschließlich vom Bereich Rechnungswesen angelegt
und müssen vom Vorstand genehmigt werden. Anträge sind mit Begründung und
voraussichtlichem Buchungsvolumen einzureichen.
""",

    "arbeitszeitrichtlinie.txt": """Arbeitszeitrichtlinie der Alpenbank AG

Stand: Februar 2024
Verantwortlich: Personalbereich

1. Geltungsbereich

Diese Richtlinie gilt für alle nicht-leitenden Angestellten der
Alpenbank AG. Für Vorstandsmitglieder, Bereichsleiter und sonstige
außertarifliche Mitarbeiter gelten gesonderte Vereinbarungen.

2. Regelarbeitszeit

Die regelmäßige wöchentliche Arbeitszeit beträgt achtunddreißig Stunden,
verteilt auf fünf Werktage. Die tägliche Sollarbeitszeit beträgt sieben
Stunden und sechsunddreißig Minuten.

3. Gleitzeit

Die Bank praktiziert ein Gleitzeitmodell mit folgenden Rahmenzeiten:
- Frühestmöglicher Arbeitsbeginn: 06:30 Uhr
- Spätestmögliches Arbeitsende: 20:00 Uhr
- Kernarbeitszeit: 09:30 Uhr bis 15:30 Uhr (Freitag bis 13:00 Uhr)

Während der Kernarbeitszeit ist die Anwesenheit verpflichtend. Abweichungen
bedürfen der Genehmigung der Führungskraft.

4. Überstunden

Überstunden fallen an, wenn die wöchentliche Sollarbeitszeit überschritten
wird. Sie sind grundsätzlich durch Freizeit auszugleichen. Eine Auszahlung
ist nur in begründeten Ausnahmefällen und nach Genehmigung durch den
Personalbereich möglich.

Die maximale Anzahl an Überstunden pro Monat beträgt vierzig Stunden. Wird
dieser Wert überschritten, ist umgehend die Führungskraft zu informieren
und ein Maßnahmenplan zur Entlastung zu erstellen.

5. Home-Office

Mitarbeiter können bis zu drei Tage pro Woche im Home-Office arbeiten,
sofern die Tätigkeit dies zulässt und die Führungskraft zustimmt. Die
Anwesenheit im Büro ist mindestens an zwei festgelegten Tagen pro Woche
verpflichtend.

Die technische Ausstattung des Heimarbeitsplatzes wird durch die Bank
gestellt. Datenschutz- und IT-Sicherheitsregeln gelten unverändert auch im
Home-Office.

6. Pausen

Bei einer Arbeitszeit von mehr als sechs Stunden ist eine Pause von
mindestens dreißig Minuten verpflichtend. Bei mehr als neun Stunden
Arbeitszeit verlängert sich die Pflichtpause auf fünfundvierzig Minuten.
Pausen zählen nicht zur Arbeitszeit.

7. Zeiterfassung

Alle Arbeitszeiten werden im internen Zeiterfassungssystem dokumentiert.
Die Erfassung erfolgt durch den Mitarbeiter selbst, eine wöchentliche
Bestätigung ist erforderlich. Manipulationen oder fehlende Einträge können
arbeitsrechtliche Konsequenzen nach sich ziehen.
""",

    "it_sicherheitsrichtlinie.txt": """IT-Sicherheitsrichtlinie der Alpenbank AG

Stand: April 2024
Verantwortlich: Bereich Informationssicherheit

1. Zweck

Diese Richtlinie legt verbindliche Regeln zum sicheren Umgang mit
informationstechnischen Systemen, Daten und Zugängen fest. Sie ist von
allen Mitarbeitern, externen Dienstleistern und Zeitkräften zu beachten.

2. Passwörter

Passwörter müssen folgende Mindestanforderungen erfüllen:
- mindestens zwölf Zeichen Länge
- mindestens ein Großbuchstabe, ein Kleinbuchstabe, eine Ziffer und ein
  Sonderzeichen
- keine Wörter aus gängigen Wörterbüchern
- keine personenbezogenen Bestandteile wie Name oder Geburtsdatum

Passwörter sind alle neunzig Tage zu wechseln. Die letzten zehn verwendeten
Passwörter dürfen nicht wiederverwendet werden. Die Weitergabe von
Passwörtern an andere Personen ist in jedem Fall untersagt, auch nicht an
die IT-Abteilung.

3. Multi-Faktor-Authentifizierung

Für alle Zugänge zu kundenbezogenen Systemen, zum Online-Banking-Backend,
zum E-Mail-Postfach und zu administrativen Systemen ist eine
Zwei-Faktor-Authentifizierung verpflichtend. Als zweiter Faktor dient die
hauseigene Authenticator-App auf dem Diensthandy.

4. Umgang mit Kundendaten

Kundendaten dürfen ausschließlich auf bankeigenen Systemen gespeichert
werden. Die lokale Speicherung auf privaten Geräten, USB-Sticks oder in
nicht freigegebenen Cloud-Diensten ist strikt untersagt.

Bei der Übermittlung von Kundendaten per E-Mail ist eine
Ende-zu-Ende-Verschlüsselung zwingend. Für den Versand größerer
Datenmengen steht das interne Datenaustauschportal zur Verfügung.

Ausdrucke mit Kundendaten sind nach Verwendung umgehend in den dafür
vorgesehenen Sicherheitstonnen zu entsorgen, niemals im allgemeinen
Papierabfall.

5. E-Mail und Phishing

Bei verdächtigen E-Mails, insbesondere mit Aufforderungen zur Eingabe von
Zugangsdaten oder zum Öffnen unerwarteter Anhänge, ist die Mail
unverzüglich an die Adresse phishing@alpenbank.ag weiterzuleiten und
anschließend zu löschen.

Auf keinen Fall dürfen Anhänge geöffnet oder Links angeklickt werden, die
nicht eindeutig als unbedenklich erkannt wurden.

6. Nutzung mobiler Endgeräte

Diensthandys und Notebooks sind mit Geräteverschlüsselung und
Bildschirmsperre zu versehen. Bei Verlust oder Diebstahl ist die
IT-Abteilung umgehend zu informieren, damit eine Fernlöschung erfolgen
kann.

Die Nutzung von dienstlichen Geräten für private Zwecke ist in begrenztem
Umfang gestattet, soweit keine sicherheitsrelevanten Risiken entstehen.

7. Verstöße

Verstöße gegen diese Richtlinie können disziplinarische Maßnahmen
einschließlich Kündigung nach sich ziehen. Schwerwiegende Verstöße werden
zusätzlich an die Aufsichtsbehörden gemeldet.
""",
}


# ---------------------------------------------------------------------------
# Funktionen
# ---------------------------------------------------------------------------


def create_schema(conn: sqlite3.Connection) -> None:
    """Legt die drei Tabellen an. Bestehende Tabellen werden vorher entfernt.

    Reihenfolge der DROPs ist wichtig: buchungen referenziert die anderen
    beiden, also muss buchungen zuerst weg.

    Foreign-Key-Constraints sind in SQLite per Default deaktiviert. Wir
    schalten sie explizit ein, damit ungültige Verweise beim Insert
    sofort auffliegen statt später bei Auswertungen Murks zu erzeugen.
    """
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        DROP TABLE IF EXISTS buchungen;
        DROP TABLE IF EXISTS konten;
        DROP TABLE IF EXISTS kostenstellen;

        CREATE TABLE kostenstellen (
            id        INTEGER PRIMARY KEY,
            name      TEXT NOT NULL,
            abteilung TEXT NOT NULL
        );

        CREATE TABLE konten (
            id          INTEGER PRIMARY KEY,
            bezeichnung TEXT NOT NULL,
            typ         TEXT NOT NULL CHECK (typ IN ('Ertrag', 'Aufwand'))
        );

        -- buchungen hat laut Konzept keine eigene id-Spalte. SQLite vergibt
        -- intern eine rowid, die für Auswertungen ausreicht.
        CREATE TABLE buchungen (
            datum            TEXT NOT NULL,
            kostenstelle_id  INTEGER NOT NULL,
            konto_id         INTEGER NOT NULL,
            betrag           REAL NOT NULL,
            FOREIGN KEY (kostenstelle_id) REFERENCES kostenstellen(id),
            FOREIGN KEY (konto_id)        REFERENCES konten(id)
        );
        """
    )


def _betrag_fuer_konto(rng: random.Random, konto_id: int) -> float:
    """Liefert einen plausiblen Betrag basierend auf der Konto-Nummer.

    Die Spannweiten orientieren sich an typischen Größenordnungen einer
    kleinen Bank (Gehälter im Zehntausender-Bereich, IT-Kosten variabel,
    Erträge mit großer Bandbreite). Reicht für ein Lernprojekt aus, um
    realistisch klingende Zahlen zu erhalten.
    """
    if konto_id < 5000:
        # Erträge: stark schwankend
        return rng.uniform(10_000, 500_000)
    if konto_id < 6100:
        # Personalkosten
        return rng.uniform(20_000, 80_000)
    if konto_id < 6200:
        # Raumkosten
        return rng.uniform(5_000, 50_000)
    if konto_id < 6300:
        # IT-Kosten
        return rng.uniform(1_000, 100_000)
    if konto_id < 6400:
        # Reisekosten – kleinere Beträge
        return rng.uniform(100, 5_000)
    if konto_id < 6500:
        # Beratung
        return rng.uniform(5_000, 50_000)
    if konto_id < 6600:
        # Marketing
        return rng.uniform(1_000, 30_000)
    # Risikovorsorge: hohe Beträge mit großer Streuung
    return rng.uniform(10_000, 200_000)


def generate_buchungen(
    rng: random.Random,
    anzahl: int = ANZAHL_BUCHUNGEN,
) -> list[tuple[str, int, int, float]]:
    """Erzeugt deterministisch Buchungs-Tupel im Schema von ``buchungen``.

    Format pro Tupel: (datum_iso, kostenstelle_id, konto_id, betrag).

    rng wird übergeben (nicht intern erzeugt), damit Tests den Seed
    kontrollieren können.
    """
    if anzahl < 0:
        raise ValueError("Anzahl darf nicht negativ sein.")

    delta_tage = (END_DATUM - START_DATUM).days
    konto_ids = [k[0] for k in KONTEN]
    kostenstelle_ids = [k[0] for k in KOSTENSTELLEN]

    buchungen: list[tuple[str, int, int, float]] = []
    for _ in range(anzahl):
        tag_offset = rng.randint(0, delta_tage)
        datum_iso = (START_DATUM + timedelta(days=tag_offset)).isoformat()
        kostenstelle = rng.choice(kostenstelle_ids)
        konto = rng.choice(konto_ids)
        # Auf Cent runden – Beträge mit zehn Nachkommastellen wirken
        # in einer Auswertung absurd.
        betrag = round(_betrag_fuer_konto(rng, konto), 2)
        buchungen.append((datum_iso, kostenstelle, konto, betrag))

    return buchungen


def seed_database(
    conn: sqlite3.Connection,
    seed: int = SEED,
    anzahl_buchungen: int = ANZAHL_BUCHUNGEN,
) -> None:
    """Schreibt Stamm- und Buchungsdaten in eine bereits angelegte Datenbank.

    Erwartet, dass ``create_schema`` zuvor lief. Ein eigenes commit am Ende
    sorgt dafür, dass die Daten auch beim Aufruf außerhalb eines
    Context-Managers persistiert werden.
    """
    rng = random.Random(seed)

    conn.executemany(
        "INSERT INTO kostenstellen (id, name, abteilung) VALUES (?, ?, ?)",
        KOSTENSTELLEN,
    )
    conn.executemany(
        "INSERT INTO konten (id, bezeichnung, typ) VALUES (?, ?, ?)",
        KONTEN,
    )

    buchungen = generate_buchungen(rng, anzahl_buchungen)
    conn.executemany(
        "INSERT INTO buchungen (datum, kostenstelle_id, konto_id, betrag) "
        "VALUES (?, ?, ?, ?)",
        buchungen,
    )
    conn.commit()


def write_documents(target_dir: Path) -> list[Path]:
    """Schreibt die fünf Textdokumente nach ``target_dir`` und liefert die Pfade.

    UTF-8 ist explizit, weil Windows sonst standardmäßig cp1252 nimmt und
    Umlaute in den Dokumenten verstümmeln würde.
    """
    target_dir.mkdir(parents=True, exist_ok=True)

    geschriebene_pfade: list[Path] = []
    for dateiname, inhalt in DOKUMENTE.items():
        pfad = target_dir / dateiname
        pfad.write_text(inhalt, encoding="utf-8")
        geschriebene_pfade.append(pfad)

    return geschriebene_pfade


def main() -> None:
    """Erzeugt die komplette Test-Umgebung: DB neu, Dokumente neu."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Frische Datenbank: ein Lauf darf den vorherigen Zustand nicht erben.
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    try:
        create_schema(conn)
        seed_database(conn)
    finally:
        conn.close()

    pfade = write_documents(DOC_DIR)

    print(f"Datenbank geschrieben: {DB_PATH}")
    print(f"  Kostenstellen: {len(KOSTENSTELLEN)}")
    print(f"  Konten:        {len(KONTEN)}")
    print(f"  Buchungen:     {ANZAHL_BUCHUNGEN}")
    print(f"Dokumente geschrieben ({len(pfade)} Stück):")
    for p in pfade:
        print(f"  - {p}")


if __name__ == "__main__":
    main()

"""Unit-Tests für scripts/daten_erzeugen.py.

Pro Funktion mindestens drei Fälle (Normal/Rand/Fehler) gemäß CLAUDE.md.
Datenbank-Tests laufen gegen ``sqlite3.connect(":memory:")``, damit die
echte Projekt-DB unter ``data/controlling.db`` nicht berührt wird.
Datei-Tests nutzen pytest's tmp_path-Fixture und schreiben in ein
temporäres Verzeichnis.
"""

from __future__ import annotations

import random
import sqlite3
from datetime import date

import pytest

from scripts import daten_erzeugen as de


# ---------------------------------------------------------------------------
# Hilfs-Fixture: in-memory DB mit frischem Schema
# ---------------------------------------------------------------------------


@pytest.fixture
def conn():
    """Liefert eine neue In-Memory-DB mit angelegtem Schema."""
    verbindung = sqlite3.connect(":memory:")
    de.create_schema(verbindung)
    yield verbindung
    verbindung.close()


# ---------------------------------------------------------------------------
# create_schema
# ---------------------------------------------------------------------------


class TestCreateSchema:
    def test_normalfall_legt_alle_drei_tabellen_an(self):
        verbindung = sqlite3.connect(":memory:")

        de.create_schema(verbindung)

        tabellen = {
            row[0]
            for row in verbindung.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"kostenstellen", "konten", "buchungen"}.issubset(tabellen)
        verbindung.close()

    def test_randfall_zweiter_aufruf_setzt_zurueck(self, conn):
        # Datensatz einfügen, dann Schema neu anlegen – die Daten müssen weg
        # sein, sonst würden zweite Läufe alte Reste mitschleppen.
        conn.execute(
            "INSERT INTO kostenstellen VALUES (9999, 'Test', 'Test')"
        )

        de.create_schema(conn)

        anzahl = conn.execute("SELECT COUNT(*) FROM kostenstellen").fetchone()[0]
        assert anzahl == 0

    def test_fehlerfall_konto_typ_check_constraint(self, conn):
        # Der CHECK-Constraint auf konten.typ verhindert Tippfehler wie
        # 'aufwand' (klein) oder ganz andere Werte. Wenn der Test rot wird,
        # ist der Constraint kaputt – das wäre ein echter Datenrisiko.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO konten VALUES (9999, 'Quatsch', 'unbekannt')"
            )


# ---------------------------------------------------------------------------
# generate_buchungen
# ---------------------------------------------------------------------------


class TestGenerateBuchungen:
    def test_normalfall_liefert_richtige_anzahl_und_struktur(self):
        rng = random.Random(0)

        buchungen = de.generate_buchungen(rng, anzahl=50)

        assert len(buchungen) == 50
        for datum_str, ks_id, konto_id, betrag in buchungen:
            # Datum muss ISO-parsebar sein und im definierten Zeitraum liegen.
            d = date.fromisoformat(datum_str)
            assert de.START_DATUM <= d <= de.END_DATUM
            # IDs müssen aus den Stammdaten stammen.
            assert ks_id in {k[0] for k in de.KOSTENSTELLEN}
            assert konto_id in {k[0] for k in de.KONTEN}
            # Beträge sollen plausibel positiv sein.
            assert betrag > 0

    def test_randfall_deterministisch_bei_gleichem_seed(self):
        # Reproduzierbarkeit ist Designziel des Skripts. Wenn dieser Test
        # rot wird, brauchen wir das Skript nicht mehr "deterministisch"
        # nennen – ein wichtiger Vertrauensanker für Lernzwecke.
        rng_a = random.Random(123)
        rng_b = random.Random(123)

        assert de.generate_buchungen(rng_a, anzahl=20) == de.generate_buchungen(
            rng_b, anzahl=20
        )

    def test_randfall_anzahl_null(self):
        rng = random.Random(0)

        assert de.generate_buchungen(rng, anzahl=0) == []

    def test_fehlerfall_negative_anzahl(self):
        rng = random.Random(0)

        with pytest.raises(ValueError, match="negativ"):
            de.generate_buchungen(rng, anzahl=-1)


# ---------------------------------------------------------------------------
# seed_database
# ---------------------------------------------------------------------------


class TestSeedDatabase:
    def test_normalfall_korrekte_anzahl_in_allen_tabellen(self, conn):
        de.seed_database(conn, seed=7, anzahl_buchungen=100)

        anzahl_ks = conn.execute("SELECT COUNT(*) FROM kostenstellen").fetchone()[0]
        anzahl_konten = conn.execute("SELECT COUNT(*) FROM konten").fetchone()[0]
        anzahl_buchungen = conn.execute(
            "SELECT COUNT(*) FROM buchungen"
        ).fetchone()[0]

        assert anzahl_ks == len(de.KOSTENSTELLEN)
        assert anzahl_konten == len(de.KONTEN)
        assert anzahl_buchungen == 100

    def test_randfall_keine_buchungen(self, conn):
        de.seed_database(conn, seed=7, anzahl_buchungen=0)

        assert conn.execute("SELECT COUNT(*) FROM buchungen").fetchone()[0] == 0
        # Stammdaten müssen trotzdem vorhanden sein.
        assert (
            conn.execute("SELECT COUNT(*) FROM kostenstellen").fetchone()[0]
            == len(de.KOSTENSTELLEN)
        )

    def test_fehlerfall_zweiter_seed_ohne_schema_reset_bricht_ab(self, conn):
        # Zweimal seeden ohne create_schema dazwischen muss scheitern,
        # weil die Stammdaten-IDs Primary Keys sind. So fällt versehentliches
        # Doppel-Seeding sofort auf.
        de.seed_database(conn, anzahl_buchungen=0)

        with pytest.raises(sqlite3.IntegrityError):
            de.seed_database(conn, anzahl_buchungen=0)


# ---------------------------------------------------------------------------
# write_documents
# ---------------------------------------------------------------------------


class TestWriteDocuments:
    def test_normalfall_alle_fuenf_dateien_und_nicht_leer(self, tmp_path):
        ziel = tmp_path / "dokumente"

        pfade = de.write_documents(ziel)

        assert len(pfade) == 5
        for p in pfade:
            assert p.exists()
            inhalt = p.read_text(encoding="utf-8")
            assert len(inhalt) > 100  # nicht leer, nicht nur Header

    def test_normalfall_dateinamen_passen_zur_konstanten(self, tmp_path):
        de.write_documents(tmp_path)

        gefundene = {p.name for p in tmp_path.iterdir() if p.suffix == ".txt"}
        assert gefundene == set(de.DOKUMENTE.keys())

    def test_randfall_zielordner_wird_angelegt(self, tmp_path):
        # Verschachtelter, noch nicht existierender Pfad – die Funktion soll
        # ihn anlegen, nicht abbrechen.
        ziel = tmp_path / "neu" / "tiefer" / "dokumente"

        de.write_documents(ziel)

        assert ziel.is_dir()
        assert len(list(ziel.glob("*.txt"))) == 5

    def test_randfall_ueberschreibt_alte_datei(self, tmp_path):
        # Wenn eine Datei mit dem gleichen Namen existiert, soll sie ohne
        # Murren ersetzt werden. Andernfalls wären wiederholte Läufe nicht
        # idempotent.
        alte_datei = tmp_path / "reisekostenrichtlinie.txt"
        alte_datei.write_text("Alter Inhalt", encoding="utf-8")

        de.write_documents(tmp_path)

        neuer_inhalt = alte_datei.read_text(encoding="utf-8")
        assert "Alpenbank" in neuer_inhalt
        assert neuer_inhalt != "Alter Inhalt"

    def test_dokumente_enthalten_erwartete_schluesselbegriffe(self, tmp_path):
        # Fachlicher Inhalts-Check: würde Schritt 2 (RAG) sinnlos werden,
        # wenn die Dokumente nicht die Begriffe enthalten, nach denen die
        # späteren Testfragen suchen.
        de.write_documents(tmp_path)

        reisekosten = (tmp_path / "reisekostenrichtlinie.txt").read_text("utf-8")
        passwoerter = (tmp_path / "it_sicherheitsrichtlinie.txt").read_text("utf-8")
        arbeitszeit = (tmp_path / "arbeitszeitrichtlinie.txt").read_text("utf-8")

        assert "Hotelkategorien" in reisekosten or "Hotel" in reisekosten
        assert "Passwort" in passwoerter or "Passwörter" in passwoerter
        assert "Überstunden" in arbeitszeit

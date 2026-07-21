"""Unit-Tests für src/sql.py.

Pro Funktion mindestens drei Fälle (Normalfall, Randfall, Fehlerfall)
gemäß CLAUDE.md. Tests dürfen die echte ``data/controlling.db`` nicht
verändern – wir legen pro Test eine eigene SQLite-Datei in ``tmp_path``
an.
"""

from __future__ import annotations

import sqlite3
import threading

import pytest

from src import sql


def _make_test_db(path) -> None:
    """Legt eine kleine SQLite-Datei mit einer Tabelle und einer Zeile an."""
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE buchung (id INTEGER PRIMARY KEY, betrag REAL)")
        conn.execute("INSERT INTO buchung (betrag) VALUES (42.5)")
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# connect
# ---------------------------------------------------------------------------


class TestConnect:
    def test_normalfall_oeffnet_verbindung_und_kann_lesen(self, tmp_path):
        db_file = tmp_path / "test.db"
        _make_test_db(db_file)

        conn = sql.connect(db_file)
        try:
            cur = conn.execute("SELECT betrag FROM buchung")
            assert cur.fetchone() == (42.5,)
        finally:
            conn.close()

    def test_randfall_verbindung_ist_read_only(self, tmp_path):
        # Schreibversuch auf der zurückgegebenen Verbindung muss
        # fehlschlagen – sonst greift der Read-Only-Schutz nicht und
        # eine versehentlich durchgerutschte Schreib-Anweisung würde
        # die Daten beschädigen.
        db_file = tmp_path / "test.db"
        _make_test_db(db_file)

        conn = sql.connect(db_file)
        try:
            with pytest.raises(sqlite3.OperationalError):
                conn.execute("INSERT INTO buchung (betrag) VALUES (1.0)")
        finally:
            conn.close()

    def test_fehlerfall_nicht_existierende_datei_wirft_filenotfound(self, tmp_path):
        nicht_da = tmp_path / "fehlt.db"

        with pytest.raises(FileNotFoundError):
            sql.connect(nicht_da)

    def test_fehlerfall_leerer_pfad_wirft_valueerror(self):
        with pytest.raises(ValueError):
            sql.connect("")

    def test_fehlerfall_none_pfad_wirft_valueerror(self):
        with pytest.raises(ValueError):
            sql.connect(None)

    def test_normalfall_connection_kann_aus_anderem_thread_genutzt_werden(
        self, tmp_path
    ):
        # Streamlit re-runt das App-Skript bei jedem Event in einem
        # anderen Thread aus seinem Worker-Pool, nutzt dabei aber die
        # gleiche gecachte Connection. Ohne check_same_thread=False
        # wirft sqlite3 dort einen ProgrammingError. Der Test sichert
        # diese Eigenschaft auf Logik-Ebene ab; der echte Streamlit-
        # Pfad bleibt davon getrennt.
        db_file = tmp_path / "test.db"
        _make_test_db(db_file)

        conn = sql.connect(db_file)
        ergebnis: list = []
        fehler: list[BaseException] = []

        def lesen_in_anderem_thread() -> None:
            try:
                cursor = conn.execute("SELECT betrag FROM buchung")
                ergebnis.append(cursor.fetchone())
            except BaseException as exc:  # noqa: BLE001
                # Wir fangen breit, weil ein ProgrammingError aus
                # sqlite3 anders wirken könnte als erwartet, und
                # wir den Test über die Outer-Assertion auswerten
                # wollen statt durch das implizite Thread-Crashen.
                fehler.append(exc)

        try:
            arbeiter = threading.Thread(target=lesen_in_anderem_thread)
            arbeiter.start()
            arbeiter.join(timeout=5)

            assert not arbeiter.is_alive(), "Thread ist hängengeblieben."
            assert not fehler, f"Fehler im anderen Thread: {fehler}"
            assert ergebnis == [(42.5,)]
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# build_schema_description
# ---------------------------------------------------------------------------


def _make_schema_test_db() -> sqlite3.Connection:
    """In-Memory-DB mit zwei Tabellen analog zur echten controlling.db.

    Wir testen gegen :memory: statt gegen Dateien, damit die Tests
    schnell bleiben und nicht mit der echten Datenbank kollidieren.
    """
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE kostenstellen (id INTEGER PRIMARY KEY, "
        "name TEXT, abteilung TEXT)"
    )
    conn.execute(
        "INSERT INTO kostenstellen VALUES (1, 'Treasury', 'Finanzen')"
    )
    conn.execute(
        "INSERT INTO kostenstellen VALUES (2, 'IT-Betrieb', 'Technik')"
    )
    conn.execute(
        "INSERT INTO kostenstellen VALUES (3, 'Vertrieb', 'Markt')"
    )
    conn.execute(
        "CREATE TABLE konten (id INTEGER PRIMARY KEY, "
        "bezeichnung TEXT, typ TEXT)"
    )
    conn.execute("INSERT INTO konten VALUES (100, 'Zinsertrag', 'Ertrag')")
    conn.commit()
    return conn


class TestBuildSchemaDescription:
    def test_normalfall_enthaelt_tabellen_ddl_und_beispielzeilen(self):
        conn = _make_schema_test_db()
        try:
            schema = sql.build_schema_description(conn)
        finally:
            conn.close()

        # Beide Tabellen, die DDL und repräsentative Werte müssen
        # auftauchen – das ist die Information, auf die Claude später
        # eine SQL-Abfrage stützt.
        assert "<datenbank>" in schema and "</datenbank>" in schema
        assert '<tabelle name="kostenstellen">' in schema
        assert '<tabelle name="konten">' in schema
        assert "CREATE TABLE kostenstellen" in schema
        assert "CREATE TABLE konten" in schema
        assert "name='Treasury'" in schema
        assert "typ='Ertrag'" in schema

    def test_normalfall_limitiert_auf_zwei_beispielzeilen(self):
        # Wir haben drei Kostenstellen eingefügt, in der Schema-Ausgabe
        # dürfen aber nur die ersten zwei erscheinen – sonst würden
        # größere Tabellen den Kontext für Claude unnötig aufblähen.
        conn = _make_schema_test_db()
        try:
            schema = sql.build_schema_description(conn)
        finally:
            conn.close()

        assert "name='Treasury'" in schema
        assert "name='IT-Betrieb'" in schema
        assert "name='Vertrieb'" not in schema

    def test_randfall_leere_datenbank_gibt_leere_huelle(self):
        conn = sqlite3.connect(":memory:")
        try:
            schema = sql.build_schema_description(conn)
        finally:
            conn.close()

        # Leere DB darf keinen Crash auslösen, sondern eine gültige
        # XML-Hülle liefern – der Aufrufer kann den String dann immer
        # gleich behandeln, ohne Sonderfall-Logik.
        assert schema == "<datenbank></datenbank>"

    def test_randfall_tabelle_ohne_daten_zeigt_marker(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE leer (id INTEGER PRIMARY KEY, label TEXT)")
        conn.commit()
        try:
            schema = sql.build_schema_description(conn)
        finally:
            conn.close()

        assert '<tabelle name="leer">' in schema
        assert "(keine Daten)" in schema

    def test_randfall_sqlite_interne_tabellen_werden_ignoriert(self):
        # sqlite_sequence wird automatisch angelegt, sobald ein
        # AUTOINCREMENT-Feld vorhanden ist – diese Verwaltungstabelle
        # gehört nicht in die fachliche Schema-Beschreibung.
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE buchung (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "betrag REAL)"
        )
        conn.execute("INSERT INTO buchung (betrag) VALUES (1.0)")
        conn.commit()
        try:
            schema = sql.build_schema_description(conn)
        finally:
            conn.close()

        assert '<tabelle name="buchung">' in schema
        assert "sqlite_sequence" not in schema

    def test_fehlerfall_none_verbindung_wirft_valueerror(self):
        with pytest.raises(ValueError):
            sql.build_schema_description(None)


# ---------------------------------------------------------------------------
# is_safe_select
# ---------------------------------------------------------------------------


class TestIsSafeSelect:
    @pytest.mark.parametrize(
        "sql_text",
        [
            "SELECT * FROM buchungen",
            "select id from konten",  # case-insensitive
            "SELECT 1;",  # trailing semicolon erlaubt
            "  SELECT 1  ",  # whitespace
            "WITH ertrag AS (SELECT * FROM buchungen) SELECT * FROM ertrag",
            "-- Kommentar mit DELETE darin\nSELECT 1",
            "/* DROP block */ SELECT 1",
            "SELECT name FROM kostenstellen WHERE name = 'Delete-Service'",
        ],
    )
    def test_normalfall_erlaubte_statements(self, sql_text):
        assert sql.is_safe_select(sql_text) is True

    @pytest.mark.parametrize(
        "sql_text",
        [
            "DELETE FROM buchungen",
            "DROP TABLE buchungen",
            "INSERT INTO konten VALUES (1, 'x', 'Ertrag')",
            "UPDATE konten SET typ='Ertrag' WHERE id=1",
            "PRAGMA foreign_keys = ON",
            "ATTACH DATABASE 'andere.db' AS andere",
            "VACUUM",
            "SELECT 1; DELETE FROM buchungen",  # mehrere Statements
            "WITH x AS (SELECT 1) DELETE FROM buchungen",  # CTE+DELETE
            "Lösch alle Buchungen!",  # natürlicher Text
            "",  # leer
            "    ",  # nur whitespace
            ";",  # nur Semikolon
        ],
    )
    def test_fehlerfall_verbotene_statements(self, sql_text):
        # is_safe_select MUSS hier False liefern, sonst rutscht eine
        # gefährliche Anweisung an die Datenbank durch. Das ist die
        # zentrale Sicherheitseigenschaft des Moduls.
        assert sql.is_safe_select(sql_text) is False

    @pytest.mark.parametrize("ungueltig", [None, 123, ["SELECT 1"], object()])
    def test_fehlerfall_kein_string_wirft_valueerror(self, ungueltig):
        with pytest.raises(ValueError):
            sql.is_safe_select(ungueltig)


# ---------------------------------------------------------------------------
# run_select
# ---------------------------------------------------------------------------


class TestRunSelect:
    def test_normalfall_liefert_zeilen_und_spalten(self):
        conn = _make_schema_test_db()
        try:
            result = sql.run_select(
                conn,
                "SELECT id, name FROM kostenstellen ORDER BY id",
            )
        finally:
            conn.close()

        assert result.columns == ["id", "name"]
        assert result.rows == [
            {"id": 1, "name": "Treasury"},
            {"id": 2, "name": "IT-Betrieb"},
            {"id": 3, "name": "Vertrieb"},
        ]

    def test_normalfall_aggregation_liefert_eine_zeile(self):
        conn = _make_schema_test_db()
        try:
            result = sql.run_select(
                conn,
                "SELECT COUNT(*) AS anzahl FROM kostenstellen",
            )
        finally:
            conn.close()

        assert result.columns == ["anzahl"]
        assert result.rows == [{"anzahl": 3}]

    def test_randfall_leeres_ergebnis_behaelt_spalten(self):
        # Auch ohne Treffer muss das Schema erhalten bleiben – sonst
        # könnte format_result_for_claude später keine Tabelle mit
        # Kopfzeile bauen.
        conn = _make_schema_test_db()
        try:
            result = sql.run_select(
                conn,
                "SELECT id, name FROM kostenstellen WHERE id = 999",
            )
        finally:
            conn.close()

        assert result.columns == ["id", "name"]
        assert result.rows == []

    def test_fehlerfall_unsafe_statement_wirft_valueerror(self):
        # Whitelist-Bypass-Versuch muss bereits hier scheitern, ohne
        # dass die DB überhaupt berührt wird.
        conn = _make_schema_test_db()
        try:
            with pytest.raises(ValueError, match="Whitelist"):
                sql.run_select(conn, "DELETE FROM kostenstellen")
            # Sicherheitsnachweis: die Tabelle wurde nicht angefasst.
            anzahl = conn.execute(
                "SELECT COUNT(*) FROM kostenstellen"
            ).fetchone()[0]
            assert anzahl == 3
        finally:
            conn.close()

    def test_fehlerfall_syntax_wird_durchgereicht(self):
        conn = _make_schema_test_db()
        try:
            with pytest.raises(sqlite3.OperationalError):
                sql.run_select(conn, "SELECT * FROM nicht_existent")
        finally:
            conn.close()

    def test_fehlerfall_none_verbindung_wirft_valueerror(self):
        with pytest.raises(ValueError):
            sql.run_select(None, "SELECT 1")

    def test_fehlerfall_none_sql_wirft_valueerror(self):
        conn = _make_schema_test_db()
        try:
            with pytest.raises(ValueError):
                sql.run_select(conn, None)
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# extract_sql_from_response
# ---------------------------------------------------------------------------


class TestExtractSqlFromResponse:
    def test_normalfall_sql_codeblock_mit_sprachkennung(self):
        antwort = "```sql\nSELECT * FROM buchungen\n```"
        assert sql.extract_sql_from_response(antwort) == "SELECT * FROM buchungen"

    def test_normalfall_codeblock_ohne_sprachkennung(self):
        # Claude lässt die Sprachkennung manchmal weg – die Extraktion
        # muss das tolerieren, sonst scheitern echte Antworten.
        antwort = "```\nSELECT 1\n```"
        assert sql.extract_sql_from_response(antwort) == "SELECT 1"

    def test_normalfall_codeblock_mit_umgebendem_text(self):
        # Auch wenn Claude erklärenden Text drumherum schreibt, ziehen
        # wir nur den Codeblock-Inhalt heraus.
        antwort = (
            "Hier ist die Abfrage:\n\n```sql\nSELECT id FROM kostenstellen\n```\n"
            "Das beantwortet die Frage."
        )
        assert (
            sql.extract_sql_from_response(antwort)
            == "SELECT id FROM kostenstellen"
        )

    def test_normalfall_nackter_sql_ohne_codeblock(self):
        # Fallback: Wenn Claude trotz Anweisung keinen Codeblock liefert,
        # akzeptieren wir den nackten SQL-Text.
        antwort = "SELECT name FROM konten"
        assert sql.extract_sql_from_response(antwort) == "SELECT name FROM konten"

    def test_normalfall_mehrzeiliges_sql_im_block(self):
        antwort = "```sql\nSELECT id, name\nFROM kostenstellen\nWHERE id = 1\n```"
        result = sql.extract_sql_from_response(antwort)
        assert "SELECT id, name" in result
        assert "FROM kostenstellen" in result
        assert "WHERE id = 1" in result

    def test_normalfall_with_cte_wird_erkannt(self):
        antwort = "```sql\nWITH t AS (SELECT 1) SELECT * FROM t\n```"
        result = sql.extract_sql_from_response(antwort)
        assert result.startswith("WITH")

    def test_fehlerfall_antwort_ohne_sql_wirft_valueerror(self):
        # Wenn Claude erklärt, warum die Frage nicht beantwortbar ist
        # (kein SELECT in der Antwort), muss die Funktion das mit
        # einem klaren Fehler signalisieren – nicht stillschweigend
        # einen erklärenden Text als SQL durchwinken.
        antwort = "Diese Frage kann ich mit dem Schema nicht beantworten."
        with pytest.raises(ValueError, match="kein erkennbares SELECT"):
            sql.extract_sql_from_response(antwort)

    def test_fehlerfall_leerer_string_wirft_valueerror(self):
        with pytest.raises(ValueError):
            sql.extract_sql_from_response("")

    def test_fehlerfall_none_wirft_valueerror(self):
        with pytest.raises(ValueError):
            sql.extract_sql_from_response(None)


# ---------------------------------------------------------------------------
# format_result_for_claude
# ---------------------------------------------------------------------------


class TestFormatResultForClaude:
    def test_normalfall_mehrere_zeilen_als_markdown_tabelle(self):
        rows = [
            {"id": 1, "name": "Treasury"},
            {"id": 2, "name": "IT-Betrieb"},
        ]
        result = sql.format_result_for_claude(rows, ["id", "name"])

        assert "| id | name |" in result
        assert "| --- | --- |" in result
        assert "| 1 | Treasury |" in result
        assert "| 2 | IT-Betrieb |" in result

    def test_normalfall_aggregations_ergebnis(self):
        # Typischer Fall für eine SUM-Abfrage – eine Zeile, eine Spalte.
        result = sql.format_result_for_claude(
            [{"summe": 12345.67}], ["summe"]
        )

        assert "| summe |" in result
        assert "| 12345.67 |" in result

    def test_normalfall_spaltenreihenfolge_aus_columns_nicht_dict(self):
        # Dict-Reihenfolge ist in Python 3.7+ stabil, aber wir dürfen
        # uns nicht darauf verlassen, dass dict-Keys mit der gewollten
        # Spaltenreihenfolge übereinstimmen – die Reihenfolge muss aus
        # ``columns`` kommen.
        rows = [{"name": "Treasury", "id": 1}]
        result = sql.format_result_for_claude(rows, ["id", "name"])

        # Auf Kopfzeilen-Ebene prüfen: id steht vor name
        kopf_zeile = result.splitlines()[0]
        assert kopf_zeile.index("id") < kopf_zeile.index("name")

    def test_randfall_leeres_ergebnis_zeigt_marker_und_kopf(self):
        # Auch ohne Treffer muss die Spaltenstruktur sichtbar sein,
        # damit Claude einen Erfolg ohne Treffer von einem Fehler
        # unterscheiden kann.
        result = sql.format_result_for_claude([], ["id", "name"])

        assert "| id | name |" in result
        assert "(keine Zeilen)" in result

    def test_randfall_none_werte_werden_als_NULL_dargestellt(self):
        result = sql.format_result_for_claude(
            [{"a": None, "b": 1}], ["a", "b"]
        )

        assert "| NULL | 1 |" in result

    def test_randfall_pipe_im_wert_wird_escaped(self):
        # Ein ungeprüftes "|" im Wert würde die Markdown-Tabelle
        # zerschießen und Claude würde Spalten falsch ausrichten.
        result = sql.format_result_for_claude(
            [{"name": "Treasury|Reserven"}], ["name"]
        )

        assert r"Treasury\|Reserven" in result

    def test_randfall_viele_zeilen_werden_abgeschnitten_mit_hinweis(self):
        rows = [{"id": i} for i in range(sql.MAX_ZEILEN_FUER_CLAUDE + 7)]
        result = sql.format_result_for_claude(rows, ["id"])

        # Hinweis muss erscheinen, sichtbare Zeilen bleiben begrenzt.
        assert "abgeschnitten" in result
        assert "7 Zeilen" in result
        assert "| 0 |" in result
        # Die letzte Zeile darf nicht durchrutschen.
        letzte_id = sql.MAX_ZEILEN_FUER_CLAUDE + 6
        assert f"| {letzte_id} |" not in result

    def test_fehlerfall_leere_spalten_wirft_valueerror(self):
        with pytest.raises(ValueError):
            sql.format_result_for_claude([], [])

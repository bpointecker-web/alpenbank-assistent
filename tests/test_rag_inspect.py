"""Tests für scripts/rag_inspect.py.

Wir testen die reinen Format- und Daten-Funktionen mit MagicMock-Collection.
Die Print-Funktionen prüfen wir mit pytest's ``capsys``-Fixture, damit wir
ohne echte ChromaDB auskommen.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from scripts import rag_inspect


# ---------------------------------------------------------------------------
# get_all_chunks
# ---------------------------------------------------------------------------


class TestGetAllChunks:
    def test_normalfall_flacht_collection_get_format_ab(self):
        collection = MagicMock()
        collection.get.return_value = {
            "ids": ["a.txt#0", "b.txt#0"],
            "documents": ["Inhalt A", "Inhalt B"],
            "metadatas": [{"quelle": "a.txt"}, {"quelle": "b.txt"}],
        }

        result = rag_inspect.get_all_chunks(collection)

        assert result == [
            {"id": "a.txt#0", "quelle": "a.txt", "inhalt": "Inhalt A"},
            {"id": "b.txt#0", "quelle": "b.txt", "inhalt": "Inhalt B"},
        ]

    def test_randfall_leere_collection(self):
        collection = MagicMock()
        collection.get.return_value = {"ids": [], "documents": [], "metadatas": []}

        assert rag_inspect.get_all_chunks(collection) == []

    def test_randfall_metadata_ohne_quelle_wird_zu_leerem_string(self):
        # Defensive: Inspect soll auch fremde Daten ohne Crash anzeigen.
        collection = MagicMock()
        collection.get.return_value = {
            "ids": ["x"],
            "documents": ["text"],
            "metadatas": [{}],
        }

        result = rag_inspect.get_all_chunks(collection)

        assert result[0]["quelle"] == ""


# ---------------------------------------------------------------------------
# format_overview_line
# ---------------------------------------------------------------------------


class TestFormatOverviewLine:
    def test_normalfall_zeigt_id_quelle_und_kurzen_inhalt(self):
        line = rag_inspect.format_overview_line(
            {"id": "a.txt#0", "quelle": "a.txt", "inhalt": "Kurzer Inhalt"}
        )

        assert "a.txt#0" in line
        assert "[a.txt]" in line
        assert "Kurzer Inhalt" in line

    def test_randfall_langer_inhalt_wird_gekuerzt(self):
        # Ohne Kürzung würde die Konsole mit einem 500-Wort-Chunk geflutet.
        langer_text = "x" * 500
        line = rag_inspect.format_overview_line(
            {"id": "a#0", "quelle": "a", "inhalt": langer_text}, auszug_laenge=50
        )

        assert "…" in line
        # Der gekürzte Auszug + Ellipsis darf den Originaltext nicht enthalten.
        assert "x" * 500 not in line

    def test_randfall_inhalt_genau_an_grenze_kein_ellipsis(self):
        line = rag_inspect.format_overview_line(
            {"id": "a#0", "quelle": "a", "inhalt": "xxxxx"}, auszug_laenge=5
        )

        assert "…" not in line


# ---------------------------------------------------------------------------
# format_search_result_line
# ---------------------------------------------------------------------------


class TestFormatSearchResultLine:
    def test_normalfall_enthaelt_distanz(self):
        line = rag_inspect.format_search_result_line(
            {
                "id": "a#0",
                "quelle": "a.txt",
                "inhalt": "irgendwas",
                "distanz": 0.123,
            }
        )

        assert "0.123" in line
        assert "a#0" in line
        assert "[a.txt]" in line

    def test_normalfall_distanz_wird_auf_drei_nachkommastellen_gerundet(self):
        line = rag_inspect.format_search_result_line(
            {
                "id": "a#0",
                "quelle": "a.txt",
                "inhalt": "x",
                "distanz": 0.1234567,
            }
        )

        # Die volle Zahl darf nicht im Output sein.
        assert "0.1234567" not in line
        assert "0.123" in line

    def test_randfall_langer_inhalt_wird_gekuerzt(self):
        line = rag_inspect.format_search_result_line(
            {
                "id": "a#0",
                "quelle": "a",
                "inhalt": "x" * 500,
                "distanz": 0.5,
            },
            auszug_laenge=20,
        )

        assert "…" in line


# ---------------------------------------------------------------------------
# print_overview – End-to-End mit capsys, ohne echte DB.
# ---------------------------------------------------------------------------


class TestPrintOverview:
    def test_normalfall_druckt_statistik_und_alle_chunks(self, capsys):
        collection = MagicMock()
        collection.get.return_value = {
            "ids": ["b.txt#0", "a.txt#0"],
            "documents": ["B-Inhalt", "A-Inhalt"],
            "metadatas": [{"quelle": "b.txt"}, {"quelle": "a.txt"}],
        }

        rag_inspect.print_overview(collection)
        out = capsys.readouterr().out

        assert "Chunks gesamt: 2" in out
        # Beide Chunks müssen erscheinen – sortiert (a vor b).
        assert out.index("a.txt#0") < out.index("b.txt#0")

    def test_randfall_leere_collection_zeigt_hinweis(self, capsys):
        collection = MagicMock()
        collection.get.return_value = {"ids": [], "documents": [], "metadatas": []}

        rag_inspect.print_overview(collection)
        out = capsys.readouterr().out

        assert "Chunks gesamt: 0" in out
        assert "keine Chunks" in out


# ---------------------------------------------------------------------------
# print_search_results
# ---------------------------------------------------------------------------


class TestPrintSearchResults:
    def test_normalfall_druckt_treffer_mit_distanz(self, capsys, monkeypatch):
        # Wir patchen rag.search, damit kein echtes Embedding-Modell geladen wird.
        treffer_dummy = [
            {
                "id": "a.txt#0",
                "quelle": "a.txt",
                "inhalt": "Hotelregeln",
                "distanz": 0.3,
            }
        ]
        monkeypatch.setattr(
            rag_inspect.rag, "search", lambda collection, frage: treffer_dummy
        )

        rag_inspect.print_search_results(MagicMock(), "Hotelfrage?")
        out = capsys.readouterr().out

        assert "Hotelfrage?" in out
        assert "Treffer (1)" in out
        assert "a.txt#0" in out
        assert "0.300" in out


# ---------------------------------------------------------------------------
# main – Argumente werden korrekt interpretiert.
# ---------------------------------------------------------------------------


class TestMain:
    def test_ohne_argument_ruft_overview_ohne_embedding(self, monkeypatch, capsys):
        coll = MagicMock()
        coll.get.return_value = {
            "ids": ["a#0"],
            "documents": ["text"],
            "metadatas": [{"quelle": "a"}],
        }
        # Wir merken uns das with_embedding-Flag, um zu prüfen, dass im
        # Overview-Modus das Modell wirklich übersprungen wird (10 s Ersparnis).
        aufruf_args = {}

        def fake_open(_path, with_embedding=True):
            aufruf_args["with_embedding"] = with_embedding
            return coll

        monkeypatch.setattr(rag_inspect, "open_existing_collection", fake_open)

        rag_inspect.main(argv=[])
        out = capsys.readouterr().out

        assert "Chunks gesamt: 1" in out
        assert aufruf_args["with_embedding"] is False

    def test_mit_argument_ruft_search_mit_embedding(self, monkeypatch, capsys):
        aufruf_args = {}

        def fake_open(_path, with_embedding=True):
            aufruf_args["with_embedding"] = with_embedding
            return MagicMock()

        monkeypatch.setattr(rag_inspect, "open_existing_collection", fake_open)
        monkeypatch.setattr(
            rag_inspect.rag,
            "search",
            lambda c, f: [
                {"id": "x", "quelle": "y", "inhalt": "z", "distanz": 0.5}
            ],
        )

        rag_inspect.main(argv=["Welche", "Hotelkategorie?"])
        out = capsys.readouterr().out

        # Mehrwortige Eingabe wird zu einer Frage zusammengefügt.
        assert "Welche Hotelkategorie?" in out
        assert "Treffer (1)" in out
        # Beim Suchen MUSS das Modell geladen werden, sonst funktioniert
        # die Vektor-Suche nicht.
        assert aufruf_args["with_embedding"] is True

    def test_fehlerfall_keine_collection_exit_code_1(self, monkeypatch, capsys):
        def failing_open(_path, with_embedding=True):
            raise FileNotFoundError("Pfad fehlt")

        monkeypatch.setattr(rag_inspect, "open_existing_collection", failing_open)

        with pytest.raises(SystemExit) as exc_info:
            rag_inspect.main(argv=[])

        assert exc_info.value.code == 1
        # Fehlermeldung muss auf stderr landen, nicht stdout, damit Pipes
        # nicht mit dem Fehler verseucht werden.
        captured = capsys.readouterr()
        assert "Pfad fehlt" in captured.err

"""Tests für scripts/rag_export_vectors.py.

Wir testen die reinen Daten- und Schreib-Funktionen mit MagicMock-Collection
und ``tmp_path`` – ohne echte ChromaDB und ohne Embedding-Modell-Ladevorgang.
"""

from __future__ import annotations

import json
import sqlite3
from unittest.mock import MagicMock

import pytest

from scripts import rag_export_vectors


# ---------------------------------------------------------------------------
# get_chunks_with_vectors
# ---------------------------------------------------------------------------


class TestGetChunksWithVectors:
    def test_normalfall_uebernimmt_id_quelle_inhalt_und_vektor(self):
        collection = MagicMock()
        collection.get.return_value = {
            "ids": ["a.txt#0", "b.txt#0"],
            "documents": ["Inhalt A", "Inhalt B"],
            "metadatas": [{"quelle": "a.txt"}, {"quelle": "b.txt"}],
            "embeddings": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
        }

        result = rag_export_vectors.get_chunks_with_vectors(collection)

        assert result == [
            {
                "id": "a.txt#0",
                "quelle": "a.txt",
                "inhalt": "Inhalt A",
                "vector": [0.1, 0.2, 0.3],
            },
            {
                "id": "b.txt#0",
                "quelle": "b.txt",
                "inhalt": "Inhalt B",
                "vector": [0.4, 0.5, 0.6],
            },
        ]

    def test_normalfall_fordert_embeddings_bei_chromadb_an(self):
        # Regression: ChromaDB liefert Embeddings nur, wenn man sie explizit
        # mit include=["embeddings"] anfordert. Wer das vergisst, bekommt
        # einen Schlüsselfehler beim Zip.
        collection = MagicMock()
        collection.get.return_value = {
            "ids": [],
            "documents": [],
            "metadatas": [],
            "embeddings": [],
        }

        rag_export_vectors.get_chunks_with_vectors(collection)

        kwargs = collection.get.call_args.kwargs
        assert "embeddings" in kwargs["include"]

    def test_randfall_leere_collection(self):
        collection = MagicMock()
        collection.get.return_value = {
            "ids": [],
            "documents": [],
            "metadatas": [],
            "embeddings": [],
        }

        assert rag_export_vectors.get_chunks_with_vectors(collection) == []

    def test_randfall_metadata_ohne_quelle_wird_zu_leerem_string(self):
        collection = MagicMock()
        collection.get.return_value = {
            "ids": ["x"],
            "documents": ["text"],
            "metadatas": [{}],
            "embeddings": [[0.0, 0.0]],
        }

        result = rag_export_vectors.get_chunks_with_vectors(collection)

        assert result[0]["quelle"] == ""


# ---------------------------------------------------------------------------
# write_export_db
# ---------------------------------------------------------------------------


def _read_back(target_path):
    """Liest die geschriebene SQLite-Datei zurück, um sie zu prüfen."""
    conn = sqlite3.connect(target_path)
    rows = conn.execute(
        "SELECT id, quelle, inhalt, dimension, vector_json FROM chunks ORDER BY id"
    ).fetchall()
    conn.close()
    return rows


class TestWriteExportDb:
    def test_normalfall_schreibt_eine_zeile_korrekt(self, tmp_path):
        target = tmp_path / "export.sqlite3"
        chunks = [
            {
                "id": "a.txt#0",
                "quelle": "a.txt",
                "inhalt": "Erster Inhalt",
                "vector": [0.1, 0.2, 0.3],
            }
        ]

        anzahl = rag_export_vectors.write_export_db(chunks, target)

        assert anzahl == 1
        rows = _read_back(target)
        assert len(rows) == 1
        chunk_id, quelle, inhalt, dim, vector_json = rows[0]
        assert chunk_id == "a.txt#0"
        assert quelle == "a.txt"
        assert inhalt == "Erster Inhalt"
        assert dim == 3
        assert json.loads(vector_json) == [0.1, 0.2, 0.3]

    def test_normalfall_idempotent_zweiter_lauf_ueberschreibt(self, tmp_path):
        # Der zweite Lauf darf nicht den Stand des ersten anhängen oder
        # einen UNIQUE-Konflikt provozieren – wir erwarten eine frische DB.
        target = tmp_path / "export.sqlite3"
        chunks_v1 = [
            {"id": "a", "quelle": "q", "inhalt": "v1", "vector": [1.0]},
        ]
        chunks_v2 = [
            {"id": "a", "quelle": "q", "inhalt": "v2", "vector": [2.0]},
            {"id": "b", "quelle": "q", "inhalt": "neu", "vector": [3.0]},
        ]

        rag_export_vectors.write_export_db(chunks_v1, target)
        rag_export_vectors.write_export_db(chunks_v2, target)

        rows = _read_back(target)
        assert len(rows) == 2
        # Erster Eintrag muss die v2-Variante sein, nicht die v1-Reste.
        assert rows[0][2] == "v2"

    def test_normalfall_mehrere_chunks(self, tmp_path):
        target = tmp_path / "export.sqlite3"
        chunks = [
            {"id": f"id{i}", "quelle": "q", "inhalt": f"text{i}", "vector": [float(i)]}
            for i in range(5)
        ]

        anzahl = rag_export_vectors.write_export_db(chunks, target)

        assert anzahl == 5
        rows = _read_back(target)
        assert len(rows) == 5

    def test_randfall_leere_liste_erzeugt_leere_tabelle(self, tmp_path):
        # Auch bei null Chunks wollen wir eine valide DB-Datei mit
        # angelegter Tabelle haben – sonst stolpert ein DB Browser-Nutzer
        # darüber, dass die Datei „kaputt" wirkt.
        target = tmp_path / "export.sqlite3"

        anzahl = rag_export_vectors.write_export_db([], target)

        assert anzahl == 0
        assert target.exists()
        rows = _read_back(target)
        assert rows == []

    def test_randfall_zielordner_wird_angelegt(self, tmp_path):
        target = tmp_path / "neuer_unterordner" / "export.sqlite3"

        rag_export_vectors.write_export_db(
            [{"id": "a", "quelle": "q", "inhalt": "t", "vector": [1.0]}], target
        )

        assert target.exists()


# ---------------------------------------------------------------------------
# main – Integration mit Mocks (ohne echte ChromaDB).
# ---------------------------------------------------------------------------


class TestMain:
    def test_normalfall_schreibt_export_und_meldet_erfolg(
        self, monkeypatch, capsys, tmp_path
    ):
        target = tmp_path / "export.sqlite3"
        coll = MagicMock()
        coll.get.return_value = {
            "ids": ["a"],
            "documents": ["text"],
            "metadatas": [{"quelle": "q"}],
            "embeddings": [[0.1, 0.2]],
        }
        monkeypatch.setattr(
            rag_export_vectors.rag_inspect,
            "open_existing_collection",
            lambda _path, with_embedding=True: coll,
        )
        monkeypatch.setattr(rag_export_vectors, "EXPORT_PATH", target)

        rag_export_vectors.main()
        out = capsys.readouterr().out

        assert "Chunks:    1" in out
        assert "Dimension: 2" in out
        assert target.exists()

    def test_fehlerfall_keine_collection_exit_code_1(self, monkeypatch, capsys):
        def failing_open(_path, with_embedding=True):
            raise FileNotFoundError("Pfad fehlt")

        monkeypatch.setattr(
            rag_export_vectors.rag_inspect,
            "open_existing_collection",
            failing_open,
        )

        with pytest.raises(SystemExit) as exc_info:
            rag_export_vectors.main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Pfad fehlt" in captured.err

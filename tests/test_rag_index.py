"""Tests für scripts/rag_index.py.

Der Hauptteil dieses Skripts ist ein End-to-End-Aufruf, der eine echte
ChromaDB persistiert und das mehrsprachige Embedding-Modell lädt. Wir
testen daher in zwei Stufen:

1. ``reset_collection`` – Wrapper-Logik mit MagicMock-Client (schnell).
2. ``build_index`` – End-to-End mit echtem Modell, geskippt per default,
   Aktivierung über ``RUN_E2E_TESTS=1``.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from scripts import rag_index


# ---------------------------------------------------------------------------
# reset_collection
# ---------------------------------------------------------------------------


def _collection_with_name(name: str):
    coll = MagicMock()
    coll.name = name
    return coll


class TestResetCollection:
    def test_normalfall_loescht_existierende_collection(self):
        client = MagicMock()
        client.list_collections.return_value = [
            _collection_with_name("alpenbank_dokumente")
        ]

        rag_index.reset_collection(client, "alpenbank_dokumente")

        client.delete_collection.assert_called_once_with(
            name="alpenbank_dokumente"
        )

    def test_randfall_collection_existiert_nicht(self):
        # Wichtig: kein Fehler, wenn die Collection neu ist (erster Lauf).
        client = MagicMock()
        client.list_collections.return_value = []

        rag_index.reset_collection(client, "alpenbank_dokumente")

        client.delete_collection.assert_not_called()

    def test_randfall_andere_collections_bleiben_unangetastet(self):
        client = MagicMock()
        client.list_collections.return_value = [
            _collection_with_name("etwas_anderes"),
            _collection_with_name("noch_was"),
        ]

        rag_index.reset_collection(client, "alpenbank_dokumente")

        client.delete_collection.assert_not_called()


# ---------------------------------------------------------------------------
# build_index – End-to-End mit echtem Embedding-Modell.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("RUN_E2E_TESTS") != "1",
    reason="E2E-Test mit echtem Embedding-Modell; aktivieren mit RUN_E2E_TESTS=1",
)
def test_e2e_build_index_persistiert_und_indexiert(tmp_path):  # pragma: no cover
    """Vollständiger Lauf gegen tmp_path – berührt data/chroma/ NICHT."""
    doc_dir = tmp_path / "dokumente"
    doc_dir.mkdir()
    (doc_dir / "doc_a.txt").write_text(
        "Dies ist ein erstes Test-Dokument mit beliebigem Inhalt.",
        encoding="utf-8",
    )
    (doc_dir / "doc_b.txt").write_text(
        "Zweites Dokument, ebenfalls kurz, für den Index-Test.",
        encoding="utf-8",
    )

    chroma_path = tmp_path / "chroma"

    # Erster Lauf: legt frisch an.
    statistik = rag_index.build_index(
        doc_dir=doc_dir,
        chroma_path=chroma_path,
        collection_name="e2e_test_collection",
    )

    assert statistik == {"dokumente": 2, "chunks": 2}
    assert chroma_path.exists()

    # Zweiter Lauf: muss idempotent sein, gleiche Statistik liefern.
    # Hier zeigt sich, dass reset_collection greift – sonst würden die
    # Chunks doppelt im Index landen oder ChromaDB würde wegen ID-Konflikt
    # abstürzen.
    statistik_zweiter_lauf = rag_index.build_index(
        doc_dir=doc_dir,
        chroma_path=chroma_path,
        collection_name="e2e_test_collection",
    )

    assert statistik_zweiter_lauf == {"dokumente": 2, "chunks": 2}

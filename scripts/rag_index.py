"""Aufbau des RAG-Vektor-Index für den Alpenbank-Assistenten.

Liest die Dokumente unter ``data/dokumente/``, zerlegt sie in überlappende
Chunks und schreibt sie in eine persistente ChromaDB unter ``data/chroma/``.

Idempotent: bei jedem Lauf wird eine eventuell vorhandene Collection
gelöscht und neu aufgebaut. So kann das Skript nach jeder
Dokumenten-Änderung wiederholt werden, ohne dass alte und neue Chunks
mischen.

Die App selbst startet dieses Skript nicht – sie öffnet die fertig
indizierte Collection (analog zu ``controlling.db``).

Aufruf aus dem Projekt-Root:
    .venv/Scripts/python.exe scripts/rag_index.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Projekt-Root in den Importpfad aufnehmen, damit "from src import rag"
# auch beim direkten Skript-Aufruf funktioniert. Bei Tests übernimmt das
# pytest.ini, hier müssen wir es selbst tun.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chromadb  # noqa: E402

from src import rag  # noqa: E402

# ---------------------------------------------------------------------------
# Pfade relativ zum Projekt-Root. Der Skript-Aufruf erwartet, dass das
# aktuelle Arbeitsverzeichnis das Projekt-Root ist.
# ---------------------------------------------------------------------------

DOC_DIR = Path("data/dokumente")
CHROMA_PATH = Path("data/chroma")


def reset_collection(client: Any, name: str) -> None:
    """Löscht die Collection, falls vorhanden – sonst no-op.

    Wir gehen über ``list_collections``, um version-unabhängig zu sein:
    direkter ``delete_collection``-Aufruf wirft je nach ChromaDB-Version
    unterschiedliche Exceptions, wenn die Collection nicht existiert.
    """
    if name in [c.name for c in client.list_collections()]:
        client.delete_collection(name=name)


def build_index(
    doc_dir: Path,
    chroma_path: Path,
    collection_name: str = rag.COLLECTION_NAME,
    embedding_function: Any | None = None,
) -> dict[str, int]:
    """Baut die Collection von Grund auf neu auf.

    Parameter sind alle injizierbar, damit Tests mit ``tmp_path`` und
    eigenen Embedding-Funktionen arbeiten können, ohne das echte
    ``data/chroma/`` zu berühren.

    Gibt eine kleine Statistik zurück (Anzahl Dokumente und Anzahl Chunks),
    damit ``main`` sie direkt ausgeben kann.
    """
    dokumente = rag.load_documents(doc_dir)
    chunks = rag.build_chunks(dokumente)

    chroma_path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(chroma_path))

    reset_collection(client, collection_name)
    collection = rag.create_collection(
        client, name=collection_name, embedding_function=embedding_function
    )
    anzahl_chunks = rag.index_chunks(collection, chunks)

    return {"dokumente": len(dokumente), "chunks": anzahl_chunks}


def main() -> None:
    statistik = build_index(DOC_DIR, CHROMA_PATH)

    print(f"RAG-Index aufgebaut unter {CHROMA_PATH}")
    print(f"  Collection:    {rag.COLLECTION_NAME}")
    print(f"  Embedding:     {rag.EMBEDDING_MODELL}")
    print(f"  Dokumente:     {statistik['dokumente']}")
    print(f"  Chunks gesamt: {statistik['chunks']}")


if __name__ == "__main__":
    main()

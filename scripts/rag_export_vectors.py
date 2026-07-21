"""Export der ChromaDB-Inhalte inklusive Embedding-Vektoren in eine
eigene, im DB Browser für SQLite einsehbare Datei.

Hintergrund: Die echte ChromaDB speichert die Vektoren binär in
``data/chroma/<uuid>/*.bin`` (HNSW-Format), nicht in der SQLite. Wer sie
visuell inspizieren will, braucht eine Export-Sicht. Dieses Skript baut
sie als ganz normale SQLite-Datei mit einer Tabelle ``chunks``:

    id           TEXT  (z. B. "reisekostenrichtlinie.txt#0")
    quelle       TEXT
    inhalt       TEXT  (voller Chunk-Text)
    dimension    INTEGER (= 384 für unser Modell)
    vector_json  TEXT  (alle Werte als JSON-Array)

Aufruf aus dem Projekt-Root:
    .venv/Scripts/python.exe scripts/rag_export_vectors.py

Anschließend ``data/chroma_with_vectors.sqlite3`` im DB Browser für
SQLite öffnen.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

# Projekt-Root in den Importpfad aufnehmen, damit "from src import rag"
# auch beim direkten Skript-Aufruf funktioniert.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import rag_inspect  # noqa: E402

# Pfade. ``CHROMA_PATH`` ist die echte (von rag_index.py befüllte) DB,
# ``EXPORT_PATH`` die generierte Inspect-Sicht. Letztere wird bei jedem
# Lauf neu erzeugt – sie ist eine Sicht, kein eigener Datenstand.
CHROMA_PATH = Path("data/chroma")
EXPORT_PATH = Path("data/chroma_with_vectors.sqlite3")


def get_chunks_with_vectors(collection: Any) -> list[dict[str, Any]]:
    """Liest alle Chunks inklusive ihrer 384-dimensionalen Vektoren aus.

    ``include=["embeddings"]`` ist Pflicht – ChromaDB liefert sonst nur
    IDs, Texte und Metadaten und spart die (großen) Vektoren ein.
    """
    rohergebnis = collection.get(include=["embeddings", "documents", "metadatas"])
    return [
        {
            "id": chunk_id,
            "quelle": metadata.get("quelle", ""),
            "inhalt": dokument,
            "vector": list(vektor),
        }
        for chunk_id, dokument, metadata, vektor in zip(
            rohergebnis["ids"],
            rohergebnis["documents"],
            rohergebnis["metadatas"],
            rohergebnis["embeddings"],
            strict=True,
        )
    ]


def write_export_db(chunks: list[dict[str, Any]], target_path: Path) -> int:
    """Schreibt die Chunks in eine frische SQLite-Datei und gibt die Anzahl zurück.

    Idempotent: existiert die Zieldatei bereits, wird sie gelöscht. Wir
    erzeugen also bei jedem Lauf einen sauberen Stand – passend zum
    Charakter „Sicht auf die ChromaDB", nicht „eigener Datenbestand".
    """
    if target_path.exists():
        target_path.unlink()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(target_path)
    try:
        conn.executescript(
            """
            CREATE TABLE chunks (
                id          TEXT PRIMARY KEY,
                quelle      TEXT NOT NULL,
                inhalt      TEXT NOT NULL,
                dimension   INTEGER NOT NULL,
                vector_json TEXT NOT NULL
            );
            """
        )
        conn.executemany(
            "INSERT INTO chunks (id, quelle, inhalt, dimension, vector_json) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (
                    chunk["id"],
                    chunk["quelle"],
                    chunk["inhalt"],
                    len(chunk["vector"]),
                    # Bewusst kompakt (kein indent), spart Platz – DB Browser
                    # kann die JSON-Zelle trotzdem als Tooltip groß anzeigen.
                    json.dumps(chunk["vector"]),
                )
                for chunk in chunks
            ],
        )
        conn.commit()
    finally:
        conn.close()

    return len(chunks)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    try:
        # with_embedding=False reicht für rein lesendes get() – die echten
        # Vektoren werden ohnehin direkt aus dem persistierten Index geladen,
        # nicht von der Embedding-Funktion neu berechnet.
        collection = rag_inspect.open_existing_collection(
            CHROMA_PATH, with_embedding=False
        )
    except (FileNotFoundError, LookupError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        sys.exit(1)

    chunks = get_chunks_with_vectors(collection)
    anzahl = write_export_db(chunks, EXPORT_PATH)

    print(f"Export geschrieben: {EXPORT_PATH}")
    print(f"  Chunks:    {anzahl}")
    if chunks:
        print(f"  Dimension: {len(chunks[0]['vector'])}")
    print()
    print("Im DB Browser für SQLite öffnen, dann z. B.:")
    print("  SELECT id, quelle, dimension, SUBSTR(vector_json, 1, 80) AS vorschau")
    print("  FROM chunks;")


if __name__ == "__main__":
    main()

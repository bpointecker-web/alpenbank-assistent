"""Inspect-Tool für die ChromaDB des Alpenbank-Assistenten.

Zwei Aufruf-Modi:

* Ohne Argument – Übersicht: Anzahl Chunks und alle Chunks mit ID,
  Quelle und kurzem Inhalts-Auszug. Lädt das Embedding-Modell **nicht**,
  ist daher schnell.

* Mit Argument – Ad-hoc-Suche: zeigt die Top-5-Treffer für die Frage,
  inklusive Distanz. Lädt das Embedding-Modell, dauert beim ersten
  Aufruf einige Sekunden.

Aufrufe aus dem Projekt-Root:

    .venv/Scripts/python.exe scripts/rag_inspect.py
    .venv/Scripts/python.exe scripts/rag_inspect.py "Welche Hotelkategorie?"
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Projekt-Root in den Importpfad aufnehmen, damit "from src import rag"
# auch beim direkten Skript-Aufruf funktioniert (analog zu rag_index.py).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chromadb  # noqa: E402

from src import rag  # noqa: E402

# Pfad zur persistierten ChromaDB. Identisch zur Konstante in rag_index.py
# und app.py – alle drei rufen aus dem Projekt-Root auf.
CHROMA_PATH = Path("data/chroma")

# Wie viele Zeichen pro Chunk-Inhalt zeigen wir an? Drei volle Sätze sind
# meist ausreichend, um zu erkennen, worum es im Chunk geht, und passen
# in eine Konsolen-Zeile.
AUSZUG_LAENGE = 200


def get_all_chunks(collection: Any) -> list[dict[str, str]]:
    """Holt alle Chunks aus der Collection in flacher Form.

    ``collection.get()`` liefert (anders als ``query``) flache Listen,
    keine Listen-von-Listen – also weniger Indirektion.

    Wirft eine eigene Exception nicht; ein leeres Ergebnis ist legitim
    (z. B. wenn das Indexierungs-Skript noch nicht gelaufen ist).
    """
    rohergebnis = collection.get()
    return [
        {
            "id": chunk_id,
            "quelle": metadata.get("quelle", ""),
            "inhalt": dokument,
        }
        for chunk_id, dokument, metadata in zip(
            rohergebnis["ids"],
            rohergebnis["documents"],
            rohergebnis["metadatas"],
            strict=True,
        )
    ]


def format_overview_line(chunk: dict[str, str], auszug_laenge: int = AUSZUG_LAENGE) -> str:
    """Baut eine einzeilige Beschreibung pro Chunk für die Übersicht."""
    inhalt = chunk["inhalt"]
    auszug = inhalt[:auszug_laenge]
    if len(inhalt) > auszug_laenge:
        auszug += " …"
    return f"  {chunk['id']:40s}  [{chunk['quelle']}]\n    {auszug}"


def format_search_result_line(
    treffer: dict[str, Any], auszug_laenge: int = AUSZUG_LAENGE
) -> str:
    """Baut eine zweizeilige Beschreibung pro Treffer mit Distanz."""
    inhalt = treffer["inhalt"]
    auszug = inhalt[:auszug_laenge]
    if len(inhalt) > auszug_laenge:
        auszug += " …"
    return (
        f"  {treffer['id']:40s}  Distanz {treffer['distanz']:.3f}  "
        f"[{treffer['quelle']}]\n    {auszug}"
    )


def open_existing_collection(chroma_path: Path, with_embedding: bool = True) -> Any:
    """Öffnet die persistierte Collection oder bricht mit klarer Meldung ab.

    ``with_embedding=False`` öffnet die Collection ohne die mehrsprachige
    Sentence-Transformer-Funktion zu instanzieren – spart ~10 s, weil das
    Modell nicht geladen wird. Reicht für reine Lese-Operationen wie
    ``collection.get()``. Für ``rag.search`` ist die Embedding-Funktion
    nötig, weil sonst die Frage nicht in einen Vektor übersetzt werden kann.
    """
    if not chroma_path.exists():
        raise FileNotFoundError(
            f"ChromaDB-Pfad {chroma_path} existiert nicht. "
            "Bitte zuerst `python scripts/rag_index.py` ausführen."
        )

    client = chromadb.PersistentClient(path=str(chroma_path))
    vorhandene = [c.name for c in client.list_collections()]
    if rag.COLLECTION_NAME not in vorhandene:
        raise LookupError(
            f"Collection '{rag.COLLECTION_NAME}' nicht in {chroma_path} "
            "gefunden. Bitte `python scripts/rag_index.py` ausführen."
        )

    if with_embedding:
        return rag.create_collection(client, name=rag.COLLECTION_NAME)
    # Ohne Embedding-Funktion. ChromaDB warnt zwar, aber für get() egal.
    return client.get_collection(name=rag.COLLECTION_NAME)


def print_overview(collection: Any) -> None:
    """Druckt Statistik plus alle Chunks. Lädt das Embedding-Modell nicht."""
    chunks = get_all_chunks(collection)
    print(f"Collection:    {rag.COLLECTION_NAME}")
    print(f"Chunks gesamt: {len(chunks)}")
    print()
    if not chunks:
        print("(keine Chunks indiziert)")
        return
    # Sortiert anzeigen, damit zwei Läufe gleich aussehen – ChromaDB
    # garantiert keine Ergebnis-Reihenfolge bei get().
    for chunk in sorted(chunks, key=lambda c: c["id"]):
        print(format_overview_line(chunk))


def print_search_results(collection: Any, frage: str) -> None:
    """Druckt die Top-5-Treffer für eine Frage, inklusive Distanz."""
    treffer = rag.search(collection, frage)
    print(f"Frage: {frage}")
    print(f"Treffer ({len(treffer)}):")
    print()
    for t in treffer:
        print(format_search_result_line(t))
        print()


def main(argv: list[str] | None = None) -> None:
    """Einstiegspunkt. Erstes Argument (falls vorhanden) ist die Suchfrage."""
    # Windows-Konsole interpretiert UTF-8 standardmäßig als cp1252 und
    # zerstört Umlaute. Reconfigure ist Pythons Bordmittel dafür. In Tests
    # hat capsys einen eigenen Stream, der reconfigure nicht unterstützt –
    # daher defensiv hinter einem Attribut-Check.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = argv if argv is not None else sys.argv[1:]

    # Im Overview-Modus brauchen wir die Embedding-Funktion nicht – das
    # spart den ~10 s Modell-Ladevorgang.
    with_embedding = bool(args)

    try:
        collection = open_existing_collection(
            CHROMA_PATH, with_embedding=with_embedding
        )
    except (FileNotFoundError, LookupError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        sys.exit(1)

    if not args:
        print_overview(collection)
    else:
        # Mehrwortige Fragen ohne Quoting in der Shell durch Joinen retten.
        frage = " ".join(args)
        print_search_results(collection, frage)


if __name__ == "__main__":
    main()

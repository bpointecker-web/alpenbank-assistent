"""RAG-Logik für den Alpenbank-Assistenten (Schritt 2).

Dieses Modul kapselt das Einlesen der Dokumente, das Zerlegen in Chunks,
den Aufbau der ChromaDB-Collection sowie die semantische Suche. Bewusst
frei von Streamlit- und Anthropic-Code, damit jede Funktion einzeln und
ohne UI / API-Key testbar ist.

Wir verwenden ein mehrsprachiges Embedding-Modell, weil unsere Dokumente
deutsch sind und das ChromaDB-Default-Modell (all-MiniLM-L6-v2) primär
auf Englisch trainiert ist.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.settings import SETTINGS

# Erweiterung der Dokumentdateien. Konstante, weil sie an mehreren Stellen
# auftauchen wird (Loading, mögliche spätere Filter beim Indexlauf).
DOKUMENT_ENDUNG = ".txt"

# Chunking-Parameter, konfigurierbar über SETTINGS (src/settings.py,
# ALPENBANK_WOERTER_PRO_CHUNK/ALPENBANK_WORT_OVERLAP). Overlap verhindert,
# dass eine inhaltlich zusammengehörige Passage genau an einer Chunk-
# Grenze zerrissen wird – dann fände die Suche einen halben Treffer.
WOERTER_PRO_CHUNK = SETTINGS.woerter_pro_chunk
WORT_OVERLAP = SETTINGS.wort_overlap

# Mehrsprachiges Sentence-Transformer-Modell. Bewusst gewählt, weil unsere
# Dokumente deutsch sind und das ChromaDB-Default-Modell (all-MiniLM-L6-v2)
# auf englische Texte trainiert wurde. Wird beim ersten Aufruf einmalig von
# Hugging Face geladen (~120 MB) und unter ~/.cache/huggingface/ gecacht.
EMBEDDING_MODELL = "paraphrase-multilingual-MiniLM-L12-v2"

# Default-Name der ChromaDB-Collection. Über Parameter überschreibbar, damit
# Tests parallel laufen und sich nicht in die Quere kommen.
COLLECTION_NAME = "alpenbank_dokumente"


def load_documents(ordner_pfad: str | Path) -> list[dict[str, str]]:
    """Liest alle Textdateien eines Ordners ein.

    Gibt eine Liste von ``{"quelle": dateiname, "inhalt": text}`` zurück,
    sortiert nach Dateinamen. Die Sortierung sorgt für deterministische
    Reihenfolge – wichtig, damit Tests und spätere Chunk-IDs reproduzierbar
    sind.

    Wir lesen ausschließlich Dateien direkt im Ordner (keine Unterordner)
    und nur Dateien mit Endung ``.txt``. Andere Dateien werden ignoriert,
    nicht etwa als Fehler gewertet – so kann später z. B. ein README im
    selben Ordner liegen, ohne den Indexlauf zu sprengen.

    Wirft ``FileNotFoundError``, wenn der Pfad nicht existiert, und
    ``NotADirectoryError``, wenn der Pfad auf eine Datei zeigt. Beides
    sind Aufrufer-Fehler, die wir laut CLAUDE.md nicht stillschweigend
    übergehen wollen.
    """
    pfad = Path(ordner_pfad)

    if not pfad.exists():
        raise FileNotFoundError(f"Ordner existiert nicht: {pfad}")
    if not pfad.is_dir():
        raise NotADirectoryError(f"Pfad ist kein Ordner: {pfad}")

    dokumente: list[dict[str, str]] = []
    for datei in sorted(pfad.iterdir()):
        if not datei.is_file() or datei.suffix.lower() != DOKUMENT_ENDUNG:
            continue
        # utf-8 ist Pflicht für deutsche Umlaute; ohne explizite Angabe
        # nimmt Python unter Windows sonst die System-Codepage (cp1252).
        inhalt = datei.read_text(encoding="utf-8")
        dokumente.append({"quelle": datei.name, "inhalt": inhalt})

    return dokumente


def chunk_text(
    text: str,
    woerter_pro_chunk: int = WOERTER_PRO_CHUNK,
    overlap: int = WORT_OVERLAP,
) -> list[str]:
    """Zerlegt einen Text in überlappende Wort-Chunks.

    Wir nutzen wortbasiertes Chunking (``text.split()``), nicht zeichenbasiertes:
    eine feste Wortzahl gibt eine besser kalkulierbare semantische Einheit als
    eine feste Zeichenzahl, und sie erzeugt keine abgeschnittenen Wörter.

    ``overlap`` gibt an, wie viele Wörter sich aufeinanderfolgende Chunks
    teilen. Eine Überlappung ist wichtig, damit eine Antwort, die zufällig
    direkt an einer Chunk-Grenze liegt, nicht in zwei halbe Treffer zerfällt.

    Achtung: Der Original-Whitespace (Tabs, mehrere Leerzeichen, Zeilenumbrüche)
    geht verloren, weil wir mit ``" "`` joinen. Für die semantische Suche
    irrelevant; falls später z. B. Code-Blöcke wichtig würden, müsste man
    die Strategie ändern.

    Wirft ``ValueError`` bei nicht-positivem ``woerter_pro_chunk``, negativem
    ``overlap`` oder ``overlap >= woerter_pro_chunk`` (sonst Endlosschleife
    bzw. negativer Schritt – beides stille Bugs, die wir hart abfangen).
    """
    if woerter_pro_chunk <= 0:
        raise ValueError(
            f"woerter_pro_chunk muss positiv sein, war {woerter_pro_chunk}."
        )
    if overlap < 0:
        raise ValueError(f"overlap darf nicht negativ sein, war {overlap}.")
    if overlap >= woerter_pro_chunk:
        raise ValueError(
            "overlap muss kleiner sein als woerter_pro_chunk "
            f"({overlap} >= {woerter_pro_chunk})."
        )

    woerter = text.split()
    if not woerter:
        return []

    schritt = woerter_pro_chunk - overlap
    chunks: list[str] = []
    start = 0
    while start < len(woerter):
        ende = start + woerter_pro_chunk
        chunks.append(" ".join(woerter[start:ende]))
        # Sobald der aktuelle Chunk das Textende abdeckt, sind wir fertig.
        # Ohne dieses Break würden wir bei einem Text knapp über einer
        # Chunk-Grenze einen winzigen, rein redundanten Overlap-Chunk anhängen.
        if ende >= len(woerter):
            break
        start += schritt

    return chunks


def build_chunks(
    dokumente: list[dict[str, str]],
    woerter_pro_chunk: int = WOERTER_PRO_CHUNK,
    overlap: int = WORT_OVERLAP,
) -> list[dict[str, str]]:
    """Verbindet Loading-Output und Chunking zu indexfertigen Einträgen.

    Erwartet eine Liste, wie sie ``load_documents`` liefert (jedes Element
    hat die Schlüssel ``quelle`` und ``inhalt``), und gibt eine flache Liste
    von Chunk-Einträgen mit den Schlüsseln ``id``, ``quelle`` und ``inhalt``
    zurück.

    Die ID hat das Format ``"<quelle>#<laufende_nummer>"``, z. B.
    ``"reisekostenrichtlinie.txt#0"``. Format ist menschenlesbar (hilft beim
    Debugging) und garantiert eindeutig, solange die Dateinamen im Ordner
    eindeutig sind – was im Dateisystem immer gilt.

    Dokumente, deren Inhalt nach dem Chunking keine Chunks ergibt (z. B.
    leere Datei), werden stillschweigend übersprungen, nicht als Fehler
    behandelt. So kann ein leeres Dokument im Ordner liegen, ohne den
    gesamten Indexlauf zu sprengen.
    """
    chunks: list[dict[str, str]] = []
    for dokument in dokumente:
        # Defensive Validierung: bei Verstoß lieber laut werden als später
        # mit kryptischem KeyError abstürzen.
        if "quelle" not in dokument or "inhalt" not in dokument:
            raise ValueError(
                "Dokument muss die Schlüssel 'quelle' und 'inhalt' enthalten, "
                f"war: {sorted(dokument.keys())}"
            )

        quelle = dokument["quelle"]
        for index, chunk_inhalt in enumerate(
            chunk_text(dokument["inhalt"], woerter_pro_chunk, overlap)
        ):
            chunks.append(
                {
                    "id": f"{quelle}#{index}",
                    "quelle": quelle,
                    "inhalt": chunk_inhalt,
                }
            )

    return chunks


def get_default_embedding_function() -> Any:
    """Liefert die mehrsprachige Standard-Embedding-Funktion.

    Lazy importiert, damit der Import von ``src.rag`` nicht zwangsweise
    ``sentence-transformers`` und PyTorch ins RAM zieht – wichtig für
    schnelle Test-Sammlung und für Aufrufer, die ihre eigene Embedding-
    Funktion mitbringen wollen.
    """
    from chromadb.utils.embedding_functions import (
        SentenceTransformerEmbeddingFunction,
    )

    return SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODELL)


def create_collection(
    client: Any,
    name: str = COLLECTION_NAME,
    embedding_function: Any | None = None,
) -> Any:
    """Holt oder erzeugt eine ChromaDB-Collection mit der gewählten Embedding-Funktion.

    Verwendet ``get_or_create_collection``, ist also idempotent: ein zweiter
    Aufruf mit demselben Namen liefert die existierende Collection zurück,
    ohne sie zu überschreiben. Wer einen frischen Index will (z. B. das
    Indexierungs-Skript), löscht die Collection vorher explizit per
    ``client.delete_collection(name)``.

    ``embedding_function`` ist optional: standardmäßig wird die mehrsprachige
    Sentence-Transformer-Funktion verwendet. Tests können hier einen Mock
    oder eine kleinere Funktion einsetzen, um den Modell-Download zu sparen.

    Wichtig: ChromaDB speichert die Embedding-Funktion an der Collection.
    Wer die Collection später wieder öffnet, MUSS dieselbe Funktion
    übergeben – sonst nutzt die Suche das Default-Modell und liefert Müll.
    """
    if not name or not name.strip():
        raise ValueError("Collection-Name darf nicht leer sein.")

    if embedding_function is None:
        embedding_function = get_default_embedding_function()

    return client.get_or_create_collection(
        name=name,
        embedding_function=embedding_function,
    )


# Pflichtschlüssel pro Chunk-Eintrag. Konstante, weil sowohl ``build_chunks``
# als auch ``index_chunks`` denselben Vertrag durchsetzen.
CHUNK_PFLICHTSCHLUESSEL = ("id", "quelle", "inhalt")


def index_chunks(collection: Any, chunks: list[dict[str, str]]) -> int:
    """Schreibt Chunks in die ChromaDB-Collection und gibt die Anzahl zurück.

    ChromaDB erwartet drei parallele Listen (``ids``, ``documents``,
    ``metadatas``) gleicher Länge und Reihenfolge. Wir bauen sie aus unserer
    Chunk-Struktur zusammen. Die Quelle wandert in die Metadaten – nicht in
    die ID –, damit wir bei Treffern später strukturiert auf
    ``treffer["metadata"]["quelle"]`` zugreifen können statt aus der ID zu
    parsen (würde z. B. bei Dateinamen mit ``#`` brechen).

    Bei einer leeren Liste rufen wir ``collection.add`` gar nicht erst auf –
    ChromaDB würde sonst mit einer wenig sprechenden Fehlermeldung abbrechen.

    Bei einem ungültigen Chunk wird ``ValueError`` geworfen, *bevor* irgendetwas
    geschrieben wird. So vermeiden wir einen halb gefüllten Index, der später
    schwer zu debuggen wäre.
    """
    if not chunks:
        return 0

    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict[str, str]] = []
    for chunk in chunks:
        if not all(schluessel in chunk for schluessel in CHUNK_PFLICHTSCHLUESSEL):
            raise ValueError(
                f"Chunk muss die Schlüssel {list(CHUNK_PFLICHTSCHLUESSEL)} "
                f"enthalten, war: {sorted(chunk.keys())}"
            )
        ids.append(chunk["id"])
        documents.append(chunk["inhalt"])
        metadatas.append({"quelle": chunk["quelle"]})

    collection.add(ids=ids, documents=documents, metadatas=metadatas)
    return len(chunks)


# Anzahl der Treffer, die wir bei einer Suche standardmäßig zurückgeben,
# konfigurierbar über SETTINGS (ALPENBANK_N_RESULTS).
DEFAULT_N_RESULTS = SETTINGS.n_results


def search(
    collection: Any,
    frage: str,
    n_results: int = DEFAULT_N_RESULTS,
) -> list[dict[str, Any]]:
    """Sucht die ``n_results`` ähnlichsten Chunks zu einer Frage.

    ChromaDB rechnet intern die Frage in einen Embedding-Vektor um, sucht
    die nächstgelegenen Chunk-Vektoren in der Collection und gibt sie
    nach Distanz aufsteigend sortiert zurück (kleinste Distanz = höchste
    Ähnlichkeit). Die Embedding-Funktion ist die, die beim Anlegen der
    Collection registriert wurde – siehe ``create_collection``.

    Wir flachen das ChromaDB-Antwortformat (Liste-von-Listen, weil die API
    auch mehrere Fragen gleichzeitig könnte) in eine einfache Liste von
    Treffer-Dicts mit Schlüsseln ``id``, ``quelle``, ``inhalt`` und
    ``distanz`` ab. Das macht den Aufrufer-Code lesbarer.

    Wenn die Collection weniger Chunks enthält als ``n_results``, gibt
    ChromaDB einfach weniger Treffer zurück – kein Fehler. Bei einer
    komplett leeren Collection bekommen wir eine leere Liste.
    """
    if not frage or not frage.strip():
        raise ValueError("Frage darf nicht leer sein.")
    if n_results <= 0:
        raise ValueError(f"n_results muss positiv sein, war {n_results}.")

    rohergebnis = collection.query(query_texts=[frage], n_results=n_results)

    # ChromaDB liefert Listen-von-Listen, weil die API mehrere Queries
    # gleichzeitig erlauben würde. Wir haben nur eine Query, also Index 0.
    ids = rohergebnis["ids"][0]
    documents = rohergebnis["documents"][0]
    metadatas = rohergebnis["metadatas"][0]
    distances = rohergebnis["distances"][0]

    return [
        {
            "id": treffer_id,
            "quelle": metadata.get("quelle", ""),
            "inhalt": dokument,
            "distanz": distanz,
        }
        for treffer_id, dokument, metadata, distanz in zip(
            ids, documents, metadatas, distances, strict=True
        )
    ]


def format_context(treffer: list[dict[str, Any]]) -> str:
    """Formatiert die Suchtreffer als XML-strukturierten Kontext-Block für Claude.

    Anthropic empfiehlt XML-Tags zur strukturierten Übergabe von Kontext, weil
    Claude diese zuverlässig erkennt und referenzieren kann. Jeder Chunk wird
    in ein ``<chunk>``-Element verpackt, dessen ``quelle``-Attribut Claude
    erlaubt, in der Antwort gezielt auf das Quelldokument zu verweisen.

    Annahme: Die Chunk-Inhalte enthalten kein XML – unsere Bank-Dokumente
    sind reiner Fließtext. Würden wir später Markdown- oder HTML-Quellen
    indizieren, müsste man die Inhalte vor dem Einbetten escapen.

    Bei leerer Trefferliste geben wir einen leeren String zurück. Der
    Aufrufer entscheidet, ob er Claude in dem Fall überhaupt etwas schickt
    oder mit "Keine relevanten Quellen gefunden" antwortet.

    Wirft ``ValueError``, wenn ein Treffer die Pflichtschlüssel ``quelle``
    oder ``inhalt`` fehlt – dann ist im Aufrufer etwas schiefgegangen, das
    wir nicht stillschweigend übergehen wollen.
    """
    if not treffer:
        return ""

    bloecke: list[str] = []
    for eintrag in treffer:
        if "quelle" not in eintrag or "inhalt" not in eintrag:
            raise ValueError(
                "Treffer muss 'quelle' und 'inhalt' enthalten, "
                f"war: {sorted(eintrag.keys())}"
            )
        bloecke.append(
            f'<chunk quelle="{eintrag["quelle"]}">\n'
            f'{eintrag["inhalt"]}\n'
            f"</chunk>"
        )

    return "<kontext>\n" + "\n".join(bloecke) + "\n</kontext>"

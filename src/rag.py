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

import re
from pathlib import Path
from typing import Any, NamedTuple
from xml.sax.saxutils import escape, quoteattr

from src.settings import SETTINGS

# Erweiterungen der Dokumentdateien, die load_documents() liest. Tupel statt
# einzelner Konstante seit Stage 2.3 (PDF-Ingestion) – reale Bank-Dokumente
# sind praktisch nie reiner Fließtext ohne Formatierung.
DOKUMENT_ENDUNGEN = (".txt", ".pdf")

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


def _lies_pdf(pfad: Path) -> str:
    """Extrahiert den Text aus einem PDF-Dokument.

    Lazy-Import von ``pypdf``, analog zu ``get_default_embedding_function``
    weiter unten – der Import von ``rag.py`` soll nicht zwangsweise
    ``pypdf`` ins RAM ziehen, wenn nur mit ``.txt``-Dokumenten gearbeitet
    wird.

    Verbindet den Text aller Seiten mit doppeltem Zeilenumbruch (trennt
    Seiten sauber, ohne Wörter zusammenzukleben). Wirft ``ValueError``, wenn
    die Datei kein lesbares PDF ist – ein defektes PDF im Ordner soll nicht
    stillschweigend übersprungen werden, das wäre ein stiller Datenverlust
    im Index.
    """
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    try:
        reader = PdfReader(str(pfad))
        seiten_text = [seite.extract_text() or "" for seite in reader.pages]
    except PyPdfError as exc:
        raise ValueError(f"Datei ist kein lesbares PDF: {pfad}") from exc

    return "\n\n".join(seiten_text)


def load_documents(ordner_pfad: str | Path) -> list[dict[str, str]]:
    """Liest alle Dokumentdateien eines Ordners ein (``.txt`` und ``.pdf``).

    Gibt eine Liste von ``{"quelle": dateiname, "inhalt": text}`` zurück,
    sortiert nach Dateinamen. Die Sortierung sorgt für deterministische
    Reihenfolge – wichtig, damit Tests und spätere Chunk-IDs reproduzierbar
    sind.

    Wir lesen ausschließlich Dateien direkt im Ordner (keine Unterordner)
    und nur Dateien mit einer Endung aus ``DOKUMENT_ENDUNGEN``. Andere
    Dateien werden ignoriert, nicht etwa als Fehler gewertet – so kann
    später z. B. ein README im selben Ordner liegen, ohne den Indexlauf zu
    sprengen. Ein PDF, das sich nicht lesen lässt, ist dagegen ein Fehler
    (siehe ``_lies_pdf``) und wird nicht stillschweigend übersprungen.

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
        if not datei.is_file() or datei.suffix.lower() not in DOKUMENT_ENDUNGEN:
            continue

        if datei.suffix.lower() == ".pdf":
            inhalt = _lies_pdf(datei)
        else:
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

    Seit Stage 4.3 werden Quelle und Inhalt XML-escaped (``xml.sax.
    saxutils``) statt der früheren, unsicheren Annahme "Chunk-Inhalte
    enthalten kein XML" – ein Dokument mit ``</chunk><chunk
    quelle="gefaelscht">`` im Text hätte sonst die Prompt-Struktur
    syntaktisch manipulieren können. Das Escaping ist die eigentliche
    technische Schutzmaßnahme; ``rag.erkenne_injektionsversuch``
    ergänzt das um eine Transparenz-Heuristik fürs Audit-Log.

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
        quelle_attr = quoteattr(eintrag["quelle"])
        inhalt_escaped = escape(eintrag["inhalt"])
        bloecke.append(
            f"<chunk quelle={quelle_attr}>\n"
            f"{inhalt_escaped}\n"
            f"</chunk>"
        )

    return "<kontext>\n" + "\n".join(bloecke) + "\n</kontext>"


# ---------------------------------------------------------------------------
# Hybrid-Search: Dense (ChromaDB) + BM25, kombiniert per Reciprocal Rank
# Fusion. Reine Keyword-Suche (BM25) und semantische Embedding-Suche
# (dense) haben unterschiedliche Schwächen: BM25 findet exakte Fachbegriffe
# und Zahlen (z. B. "Kostenstelle 4711", "Kilometergeld") zuverlässig, auch
# wenn das Embedding-Modell sie semantisch falsch einordnet; dense findet
# sinnverwandte Formulierungen, die BM25 mangels Wortüberlappung übersieht.
# RRF kombiniert beide Rangfolgen, ohne dass ihre Rohwerte (Cosine-Distanz
# vs. BM25-Score) vergleichbar sein müssen – nur die Rangposition zählt.
# ---------------------------------------------------------------------------


class Bm25Index(NamedTuple):
    """Gebündelter In-Memory-BM25-Index.

    ``bm25`` ist die trainierte ``BM25Okapi``-Instanz, ``eintraege`` die
    parallele Liste der Chunk-Metadaten (id/quelle/inhalt) in exakt der
    Reihenfolge, die beim Tokenisieren verwendet wurde – ``bm25_search``
    braucht diese Zuordnung, um BM25-Scores wieder auf vollständige
    Treffer-Dicts abzubilden (``BM25Okapi`` selbst kennt nur Positionen,
    keine IDs).
    """

    bm25: Any
    eintraege: list[dict[str, Any]]


class RagIndex(NamedTuple):
    """Bündelt alle Retrieval-Komponenten für den Tool-Use-Agenten.

    Ersetzt seit Stage 2.4 die einzelne ``collection`` als Parameter in
    ``agent.execute_tool``/``agent.answer_question`` – Hybrid-Search
    braucht sowohl die ChromaDB-Collection (dense) als auch den
    BM25-Index (Keyword); seit Stage 2.5 zusätzlich den Cross-Encoder
    fürs Reranking. Ein weiterer Einzelparameter pro Komponente wäre
    unübersichtlich geworden.
    """

    collection: Any
    bm25_index: Bm25Index
    reranker: Any


_TOKEN_PATTERN = re.compile(r"[a-zäöüß0-9]+")


def _tokenize(text: str) -> list[str]:
    """Zerlegt einen Text in lowercase Wort-Tokens für BM25.

    Einfache Regex-Tokenisierung statt eines NLP-Tokenizers (z. B. spaCy):
    reicht für unseren kleinen deutschen Corpus, ohne eine weitere
    Abhängigkeit einzuführen. Zahlen bleiben als eigene Tokens erhalten,
    weil Kostenstellen-/Kontonummern (z. B. "4711") für die Keyword-Suche
    relevant sind.
    """
    return _TOKEN_PATTERN.findall(text.lower())


def build_bm25_index(collection: Any) -> Bm25Index:
    """Baut einen In-Memory-BM25-Index aus allen Chunks einer Collection.

    Wird einmalig pro Prozess/Session aufgerufen (siehe
    ``app.py::open_bm25_index``), nicht pro Suchanfrage – Tokenisieren von
    ~20 kurzen Chunks kostet Millisekunden. Kein zusätzliches persistentes
    Artefakt neben ChromaDB: das würde nur ein Synchronisationsrisiko
    schaffen (BM25-Index veraltet, wenn ``data/chroma/`` neu aufgebaut
    wird, der BM25-Cache aber nicht).

    ``collection.get()`` liefert flache Listen (anders als ``query()``,
    das Listen-von-Listen liefert).

    Wirft ``ValueError`` bei einer leeren Collection: ``BM25Okapi`` bricht
    bei einem leeren Corpus mit einer kryptischen ``ZeroDivisionError``
    ab (interne Idf-Mittelwertberechnung teilt durch die Dokumentanzahl).
    Eine leere Collection ist ein Konfigurationsfehler (Indexierungs-
    Skript wurde nicht ausgeführt), kein legitimer Laufzeitzustand – den
    wollen wir mit einer sprechenden Meldung abfangen, bevor die
    kryptische Exception den Nutzer erreicht.
    """
    from rank_bm25 import BM25Okapi

    rohergebnis = collection.get()
    ids = rohergebnis["ids"]
    documents = rohergebnis["documents"]
    metadatas = rohergebnis["metadatas"]

    if not ids:
        raise ValueError(
            "Collection enthält keine Chunks. Bitte zuerst "
            "`python scripts/rag_index.py` ausführen."
        )

    bm25 = BM25Okapi([_tokenize(dokument) for dokument in documents])
    eintraege = [
        {"id": chunk_id, "quelle": metadata.get("quelle", ""), "inhalt": dokument}
        for chunk_id, dokument, metadata in zip(
            ids, documents, metadatas, strict=True
        )
    ]

    return Bm25Index(bm25=bm25, eintraege=eintraege)


def bm25_search(
    bm25_index: Bm25Index,
    frage: str,
    n_results: int = DEFAULT_N_RESULTS,
) -> list[dict[str, Any]]:
    """Sucht die ``n_results`` besten Treffer per BM25-Keyword-Score.

    Rückgabeform bewusst analog zu ``search()``: Liste von Dicts mit
    ``id``/``quelle``/``inhalt`` – hier zusätzlich ``score`` (BM25-Wert,
    höher = relevanter; anders als die Cosine-``distanz`` bei ``search()``,
    wo niedriger = relevanter ist). ``reciprocal_rank_fusion`` braucht nur
    die Rangfolge, nicht den Rohwert, daher ist diese unterschiedliche
    Semantik hier unschädlich.

    Wirft ``ValueError`` bei leerer Frage oder nicht-positivem
    ``n_results`` (analog ``search()``).
    """
    if not frage or not frage.strip():
        raise ValueError("Frage darf nicht leer sein.")
    if n_results <= 0:
        raise ValueError(f"n_results muss positiv sein, war {n_results}.")

    tokens = _tokenize(frage)
    scores = bm25_index.bm25.get_scores(tokens)

    reihenfolge = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[
        :n_results
    ]

    return [
        {
            "id": bm25_index.eintraege[i]["id"],
            "quelle": bm25_index.eintraege[i]["quelle"],
            "inhalt": bm25_index.eintraege[i]["inhalt"],
            "score": float(scores[i]),
        }
        for i in reihenfolge
    ]


# Dämpfungsfaktor für Reciprocal Rank Fusion – 60 ist der in der Literatur
# gängige Standardwert (Cormack et al., 2009). Verhindert, dass ein
# Spitzenplatz in nur einer der beiden Rangfolgen einen unverhältnismäßig
# hohen Fusions-Score erzeugt.
RRF_K = 60


def reciprocal_rank_fusion(
    rankings: list[list[str]], k: int = RRF_K
) -> list[tuple[str, float]]:
    """Fusioniert mehrere Rangfolgen (z. B. dense + BM25) per RRF.

    Jede Rangfolge ist eine Liste von Chunk-IDs, beste Übereinstimmung
    zuerst. Ein Dokument, das in mehreren Rangfolgen weit oben steht,
    bekommt einen hohen Fusions-Score. RRF braucht dafür keine
    vergleichbaren Rohwerte (Cosine-Distanz und BM25-Score sind nicht
    direkt vergleichbar) – nur die Rangposition zählt:

        score(d) = Summe über alle Rangfolgen r, die d enthalten,
                   von 1 / (k + rang_r(d))

    Reine Funktion ohne Seiteneffekte, deshalb ohne Mocks testbar. Gibt
    ``(id, score)``-Paare zurück, absteigend nach Score sortiert. Wirft
    ``ValueError`` bei ``k <= 0``.
    """
    if k <= 0:
        raise ValueError(f"k muss positiv sein, war {k}.")

    scores: dict[str, float] = {}
    for rangfolge in rankings:
        for rang, chunk_id in enumerate(rangfolge, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rang)

    return sorted(scores.items(), key=lambda paar: paar[1], reverse=True)


# Wie viele Kandidaten wir vor der Fusion aus JEDER Suchmethode holen.
# Größer als n_results, damit RRF genug Auswahl hat, um Treffer
# hochzuspülen, die in einer Methode weiter unten, in der anderen aber
# ganz oben stehen.
HYBRID_CANDIDATE_MULTIPLIER = 4


def hybrid_search(
    collection: Any,
    bm25_index: Bm25Index,
    frage: str,
    n_results: int = DEFAULT_N_RESULTS,
) -> list[dict[str, Any]]:
    """Kombiniert Dense- (ChromaDB) und BM25-Suche per Reciprocal Rank Fusion.

    Holt von beiden Suchmethoden ``n_results * HYBRID_CANDIDATE_MULTIPLIER``
    Kandidaten (mehr Auswahl für die Fusion als am Ende gebraucht wird),
    fusioniert die beiden Rangfolgen und gibt die ``n_results`` besten
    zurück. Rückgabeform wie ``search()``: Liste von Dicts mit
    ``id``/``quelle``/``inhalt`` – statt ``distanz`` jetzt
    ``fusion_score`` (höher = relevanter, andere Semantik als die
    bisherige Distanz).

    Wirft ``ValueError`` bei leerer Frage oder nicht-positivem
    ``n_results`` (analog ``search()``/``bm25_search()``).
    """
    if not frage or not frage.strip():
        raise ValueError("Frage darf nicht leer sein.")
    if n_results <= 0:
        raise ValueError(f"n_results muss positiv sein, war {n_results}.")

    n_kandidaten = n_results * HYBRID_CANDIDATE_MULTIPLIER
    dense_treffer = search(collection, frage, n_results=n_kandidaten)
    bm25_treffer = bm25_search(bm25_index, frage, n_results=n_kandidaten)

    # Lookup für quelle/inhalt nach der Fusion: RRF kennt nur IDs und
    # Scores, nicht die Chunk-Inhalte. Beide Trefferlisten zusammen
    # decken jede ID ab, die in der fusionierten Rangfolge auftauchen
    # kann – eine ID kann nur fusioniert werden, wenn sie in mindestens
    # einer der beiden Listen vorkam.
    lookup = {t["id"]: t for t in dense_treffer}
    lookup.update({t["id"]: t for t in bm25_treffer})

    fusioniert = reciprocal_rank_fusion(
        [
            [t["id"] for t in dense_treffer],
            [t["id"] for t in bm25_treffer],
        ]
    )

    return [
        {
            "id": chunk_id,
            "quelle": lookup[chunk_id]["quelle"],
            "inhalt": lookup[chunk_id]["inhalt"],
            "fusion_score": score,
        }
        for chunk_id, score in fusioniert[:n_results]
    ]


# ---------------------------------------------------------------------------
# Cross-Encoder-Reranking. Ein Cross-Encoder liest Frage und Chunk
# GEMEINSAM (statt wie Embeddings getrennt in Vektoren zu kodieren und
# per Cosine-Similarity zu vergleichen) und bewertet die Relevanz direkt –
# präziser, aber pro Kandidat teurer. Deshalb erst NACH der günstigeren
# Hybrid-Vorauswahl (RERANK_CANDIDATE_POOL Kandidaten) einsetzen, nicht auf
# dem gesamten Corpus.
# ---------------------------------------------------------------------------

# Mehrsprachiges Cross-Encoder-Modell (gleiche MiniLM-Modellfamilie wie
# EMBEDDING_MODELL, konsistente Tooling-Geschichte). Bewusst das kleine
# Modell (~200 MB) statt eines State-of-the-Art-Modells wie
# BAAI/bge-reranker-v2-m3 (~2 GB): bei nur RERANK_CANDIDATE_POOL
# Kandidaten aus einem kleinen Corpus ist der Qualitätsgewinn des
# größeren Modells kaum spürbar, das Downloadrisiko auf Windows
# (sentence-transformers-Kette, siehe pyarrow-Stolperstein oben) aber
# deutlich höher.
RERANKER_MODELL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"

# Wie viele Kandidaten hybrid_search() liefern soll, bevor rerank() sie
# auf DEFAULT_N_RESULTS filtert. Größer als der finale n_results, damit
# der Cross-Encoder aus einer breiteren Vorauswahl schöpfen kann.
RERANK_CANDIDATE_POOL = 20


def get_default_reranker() -> Any:
    """Liefert den Standard-Cross-Encoder für Reranking.

    Lazy importiert, analog zu ``get_default_embedding_function()`` – der
    Import von ``rag.py`` soll nicht zwangsweise ``sentence-transformers``
    samt Cross-Encoder-Modell ins RAM ziehen.
    """
    from sentence_transformers import CrossEncoder

    return CrossEncoder(RERANKER_MODELL)


def rerank(
    frage: str,
    kandidaten: list[dict[str, Any]],
    reranker: Any | None = None,
    top_n: int = DEFAULT_N_RESULTS,
) -> list[dict[str, Any]]:
    """Reranked Hybrid-Search-Kandidaten mit einem Cross-Encoder auf ``top_n``.

    Ergänzt die Treffer-Dicts additiv um ``rerank_score`` (höher =
    relevanter), ersetzt bestehende Schlüssel (u. a. ``fusion_score``)
    nicht – geringeres Risiko für Aufrufer, die noch auf die alten Felder
    zugreifen.

    Bei leeren Kandidaten wird der Reranker gar nicht erst aufgerufen –
    unnötige Modell-Inferenz sparen. ``reranker`` ist optional (Default:
    ``get_default_reranker()``), analog zum ``embedding_function``-Muster
    bei ``create_collection`` – Tests können hier einen Mock einsetzen, um
    den Modell-Download zu sparen.

    Wirft ``ValueError`` bei leerer Frage oder nicht-positivem ``top_n``.
    """
    if not frage or not frage.strip():
        raise ValueError("Frage darf nicht leer sein.")
    if top_n <= 0:
        raise ValueError(f"top_n muss positiv sein, war {top_n}.")

    if not kandidaten:
        return []

    if reranker is None:
        reranker = get_default_reranker()

    paare = [(frage, kandidat["inhalt"]) for kandidat in kandidaten]
    scores = reranker.predict(paare)

    bewertet = [
        {**kandidat, "rerank_score": float(score)}
        for kandidat, score in zip(kandidaten, scores, strict=True)
    ]
    bewertet.sort(key=lambda k: k["rerank_score"], reverse=True)

    return bewertet[:top_n]


# ---------------------------------------------------------------------------
# Prompt-Injection-Heuristik (Stage 4.3). Reine Substring-Suche, kein ML-
# Klassifikator - der eigentliche technische Schutz ist das XML-Escaping
# in format_context() (verhindert, dass Chunk-Inhalt die Prompt-Struktur
# syntaktisch manipuliert). Diese Heuristik dient der TRANSPARENZ
# (Audit-Log, Governance-Panel): "wurde hier ein Manipulationsversuch
# erkannt" - nicht als alleinige Verteidigungslinie.
# ---------------------------------------------------------------------------

INJEKTIONS_MUSTER: tuple[str, ...] = (
    "system:",
    "ignoriere alle vorherigen anweisungen",
    "ignoriere die vorherigen anweisungen",
    "neue anweisung:",
    "###system",
    "you are now",
    "act as",
    "ignore all previous instructions",
    "ignore previous instructions",
)


def erkenne_injektionsversuch(text: str) -> list[str]:
    """Erkennt verdächtige Muster in einem Chunk-Inhalt (Heuristik).

    Case-insensitive Substring-Suche gegen ``INJEKTIONS_MUSTER``. Gibt
    die Liste der gefundenen Muster zurück (leer = nichts gefunden).
    Wirft keine Exception – ein False Positive soll die Antwort nicht
    verhindern, nur sichtbar machen.
    """
    text_lower = text.lower()
    return [muster for muster in INJEKTIONS_MUSTER if muster in text_lower]

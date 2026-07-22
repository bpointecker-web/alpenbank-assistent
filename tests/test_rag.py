"""Unit-Tests für src/rag.py.

Pro Funktion mindestens drei Fälle (Normalfall, Randfall, Fehlerfall) gemäß
CLAUDE.md. Tests, die ChromaDB nutzen, werden später so geschrieben, dass
sie nur in einem Temp-Ordner arbeiten – die echte ``data/chroma/`` darf
durch Tests nicht verändert werden.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src import rag

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# load_documents
# ---------------------------------------------------------------------------


class TestLoadDocuments:
    def test_normalfall_liest_alle_txt_dateien_sortiert(self, tmp_path):
        # Bewusst in umgekehrter Reihenfolge anlegen, um die Sortierung
        # echt zu prüfen – sonst könnte das OS zufällig schon sortieren.
        (tmp_path / "b.txt").write_text("Inhalt B", encoding="utf-8")
        (tmp_path / "a.txt").write_text("Inhalt A", encoding="utf-8")

        result = rag.load_documents(tmp_path)

        assert result == [
            {"quelle": "a.txt", "inhalt": "Inhalt A"},
            {"quelle": "b.txt", "inhalt": "Inhalt B"},
        ]

    def test_normalfall_deutsche_umlaute_werden_korrekt_gelesen(self, tmp_path):
        # Regression gegen einen klassischen Windows-Bug: ohne explizites
        # encoding="utf-8" liest Python die Datei in cp1252 und Umlaute
        # werden zerstört.
        (tmp_path / "umlaute.txt").write_text(
            "Ärger mit Übermut und Größe", encoding="utf-8"
        )

        result = rag.load_documents(tmp_path)

        assert result[0]["inhalt"] == "Ärger mit Übermut und Größe"

    def test_randfall_leerer_ordner_gibt_leere_liste(self, tmp_path):
        assert rag.load_documents(tmp_path) == []

    def test_randfall_nicht_unterstuetzte_dateien_werden_ignoriert(self, tmp_path):
        (tmp_path / "richtlinie.txt").write_text("ja", encoding="utf-8")
        (tmp_path / "README.md").write_text("nein", encoding="utf-8")
        (tmp_path / "bild.png").write_bytes(b"\x89PNG")
        (tmp_path / "unterordner").mkdir()

        result = rag.load_documents(tmp_path)

        assert result == [{"quelle": "richtlinie.txt", "inhalt": "ja"}]

    def test_fehlerfall_nicht_existenter_ordner(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="existiert nicht"):
            rag.load_documents(tmp_path / "gibt_es_nicht")

    def test_fehlerfall_pfad_ist_datei(self, tmp_path):
        datei = tmp_path / "ich_bin_eine_datei.txt"
        datei.write_text("hallo", encoding="utf-8")

        with pytest.raises(NotADirectoryError, match="kein Ordner"):
            rag.load_documents(datei)

    def test_normalfall_pdf_datei_wird_gelesen(self, tmp_path):
        shutil.copy(FIXTURES_DIR / "beispiel.pdf", tmp_path / "beispiel.pdf")

        result = rag.load_documents(tmp_path)

        assert len(result) == 1
        assert result[0]["quelle"] == "beispiel.pdf"
        assert "Testrichtlinie" in result[0]["inhalt"]
        assert "Umlauten" in result[0]["inhalt"]

    def test_normalfall_txt_und_pdf_gemeinsam_sortiert(self, tmp_path):
        (tmp_path / "b_dokument.txt").write_text("Text-Inhalt", encoding="utf-8")
        shutil.copy(FIXTURES_DIR / "beispiel.pdf", tmp_path / "a_dokument.pdf")

        result = rag.load_documents(tmp_path)

        assert [d["quelle"] for d in result] == ["a_dokument.pdf", "b_dokument.txt"]

    def test_randfall_pdf_ohne_extrahierbaren_text(self, tmp_path):
        # Ein valides PDF mit einer leeren Seite - pypdf liefert dafür
        # keinen Fehler, sondern einen leeren String. Das ist keine
        # defekte Datei, sondern schlicht ein Dokument ohne Text (z. B.
        # ein eingescanntes Bild ohne OCR-Schicht).
        from pypdf import PdfWriter

        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        pdf_pfad = tmp_path / "leer.pdf"
        with pdf_pfad.open("wb") as datei:
            writer.write(datei)

        result = rag.load_documents(tmp_path)

        assert result == [{"quelle": "leer.pdf", "inhalt": ""}]

    def test_fehlerfall_korruptes_pdf(self, tmp_path):
        shutil.copy(FIXTURES_DIR / "kaputt.pdf", tmp_path / "kaputt.pdf")

        with pytest.raises(ValueError, match="kein lesbares PDF"):
            rag.load_documents(tmp_path)


# ---------------------------------------------------------------------------
# chunk_text
# ---------------------------------------------------------------------------


class TestChunkText:
    def test_normalfall_text_kuerzer_als_chunk_ergibt_einen_chunk(self):
        text = "Dies ist ein kurzer Beispieltext mit wenigen Wörtern."

        chunks = rag.chunk_text(text, woerter_pro_chunk=500, overlap=50)

        assert chunks == [text]

    def test_normalfall_chunkt_genau_an_der_grenze(self):
        # Bei genau 500 Wörtern soll es nur einen Chunk geben, keinen
        # leeren Folge-Chunk durch den Overlap.
        text = " ".join(f"wort{i}" for i in range(500))

        chunks = rag.chunk_text(text, woerter_pro_chunk=500, overlap=50)

        assert len(chunks) == 1
        assert chunks[0].split()[-1] == "wort499"

    def test_normalfall_overlap_funktioniert(self):
        # 1000 Wörter, Chunkgröße 100, Overlap 20 → Schritt 80.
        # Erwartete Chunks: [0..100), [80..180), [160..260), ... [880..980), [960..1000).
        text = " ".join(f"w{i}" for i in range(1000))

        chunks = rag.chunk_text(text, woerter_pro_chunk=100, overlap=20)

        # Erster Chunk endet bei w99, zweiter beginnt bei w80 – das sind die
        # 20 Overlap-Wörter, die beiden Chunks gemeinsam sind.
        erster_chunk_woerter = chunks[0].split()
        zweiter_chunk_woerter = chunks[1].split()
        assert erster_chunk_woerter[-20:] == zweiter_chunk_woerter[:20]

    def test_normalfall_letzter_chunk_kann_kuerzer_sein(self):
        # 250 Wörter bei Chunkgröße 100 / Overlap 20 (Schritt 80):
        # [0..100), [80..180), [160..250). Der letzte hat 90 Wörter.
        text = " ".join(f"w{i}" for i in range(250))

        chunks = rag.chunk_text(text, woerter_pro_chunk=100, overlap=20)

        assert len(chunks) == 3
        assert len(chunks[-1].split()) == 90
        assert chunks[-1].split()[-1] == "w249"

    def test_randfall_leerer_text(self):
        assert rag.chunk_text("", woerter_pro_chunk=500, overlap=50) == []

    def test_randfall_nur_whitespace(self):
        # split() liefert für reinen Whitespace eine leere Liste – also
        # konsequent leere Chunk-Liste.
        assert rag.chunk_text("   \n\t  ", woerter_pro_chunk=500, overlap=50) == []

    def test_fehlerfall_chunkgroesse_null(self):
        with pytest.raises(ValueError, match="muss positiv sein"):
            rag.chunk_text("text", woerter_pro_chunk=0, overlap=0)

    def test_fehlerfall_chunkgroesse_negativ(self):
        with pytest.raises(ValueError, match="muss positiv sein"):
            rag.chunk_text("text", woerter_pro_chunk=-5, overlap=0)

    def test_fehlerfall_overlap_negativ(self):
        with pytest.raises(ValueError, match="overlap darf nicht negativ"):
            rag.chunk_text("text", woerter_pro_chunk=100, overlap=-1)

    def test_fehlerfall_overlap_groesser_gleich_chunkgroesse(self):
        # Würde sonst zu Schritt 0 (Endlosschleife) oder negativem Schritt
        # führen – muss daher hart abgewiesen werden.
        with pytest.raises(ValueError, match="overlap muss kleiner"):
            rag.chunk_text("text", woerter_pro_chunk=100, overlap=100)


# ---------------------------------------------------------------------------
# build_chunks
# ---------------------------------------------------------------------------


class TestBuildChunks:
    def test_normalfall_erzeugt_eintraege_mit_id_quelle_inhalt(self):
        # Kleine Chunkgröße (3 Wörter, 1 Overlap) macht das Verhalten an
        # einem überschaubaren Beispiel nachvollziehbar.
        dokumente = [
            {"quelle": "a.txt", "inhalt": "eins zwei drei vier fünf"},
            {"quelle": "b.txt", "inhalt": "alpha beta"},
        ]

        chunks = rag.build_chunks(dokumente, woerter_pro_chunk=3, overlap=1)

        # a.txt: [eins zwei drei], [drei vier fünf]  → 2 Chunks
        # b.txt: [alpha beta]                         → 1 Chunk
        assert chunks == [
            {"id": "a.txt#0", "quelle": "a.txt", "inhalt": "eins zwei drei"},
            {"id": "a.txt#1", "quelle": "a.txt", "inhalt": "drei vier fünf"},
            {"id": "b.txt#0", "quelle": "b.txt", "inhalt": "alpha beta"},
        ]

    def test_normalfall_ids_sind_eindeutig(self):
        dokumente = [
            {"quelle": "x.txt", "inhalt": " ".join(f"w{i}" for i in range(250))},
            {"quelle": "y.txt", "inhalt": " ".join(f"v{i}" for i in range(120))},
        ]

        chunks = rag.build_chunks(dokumente, woerter_pro_chunk=100, overlap=20)

        ids = [c["id"] for c in chunks]
        assert len(ids) == len(set(ids)), f"IDs nicht eindeutig: {ids}"

    def test_randfall_leere_dokumentliste(self):
        assert rag.build_chunks([]) == []

    def test_randfall_leerer_inhalt_wird_uebersprungen(self):
        # Ein Dokument ohne Inhalt produziert keine Chunks – aber die
        # anderen Dokumente werden trotzdem verarbeitet.
        dokumente = [
            {"quelle": "leer.txt", "inhalt": "   "},
            {"quelle": "voll.txt", "inhalt": "ein bisschen text"},
        ]

        chunks = rag.build_chunks(dokumente, woerter_pro_chunk=10, overlap=2)

        assert [c["quelle"] for c in chunks] == ["voll.txt"]
        assert chunks[0]["id"] == "voll.txt#0"

    def test_fehlerfall_dokument_ohne_pflichtschluessel(self):
        with pytest.raises(ValueError, match="quelle.*inhalt"):
            rag.build_chunks([{"quelle": "a.txt"}])  # 'inhalt' fehlt

    def test_fehlerfall_leeres_dict(self):
        with pytest.raises(ValueError, match="quelle.*inhalt"):
            rag.build_chunks([{}])


# ---------------------------------------------------------------------------
# create_collection
#
# Wir testen hier bewusst nur unsere dünne Wrapper-Logik mit MagicMock-Client
# und Mock-Embedding-Funktion. Würden wir die echte SentenceTransformer-
# Funktion instanziieren, lädt das Modell ~70 s beim ersten Lauf und macht
# die Test-Suite unbrauchbar. Ein End-to-End-Test mit echter Embedding-
# Funktion folgt bei den Suche-Tests.
# ---------------------------------------------------------------------------


class TestCreateCollection:
    def test_normalfall_uebergibt_namen_und_embedding_function(self):
        client = MagicMock()
        client.get_or_create_collection.return_value = "fake_collection"
        embedding_function = MagicMock()

        result = rag.create_collection(
            client, name="test_coll", embedding_function=embedding_function
        )

        assert result == "fake_collection"
        client.get_or_create_collection.assert_called_once_with(
            name="test_coll",
            embedding_function=embedding_function,
        )

    def test_normalfall_default_name_wird_verwendet(self):
        client = MagicMock()

        rag.create_collection(client, embedding_function=MagicMock())

        # Default-Name muss aus der Modul-Konstante stammen, damit Index-Skript
        # und App garantiert dieselbe Collection treffen.
        kwargs = client.get_or_create_collection.call_args.kwargs
        assert kwargs["name"] == rag.COLLECTION_NAME

    def test_normalfall_default_embedding_function_wird_geladen(self, monkeypatch):
        # Wir patchen get_default_embedding_function, damit kein echtes Modell
        # geladen wird – wir wollen nur prüfen, dass der Wrapper bei fehlender
        # Embedding-Funktion die Default-Loader-Funktion aufruft.
        sentinel = object()
        monkeypatch.setattr(rag, "get_default_embedding_function", lambda: sentinel)
        client = MagicMock()

        rag.create_collection(client, name="x")

        kwargs = client.get_or_create_collection.call_args.kwargs
        assert kwargs["embedding_function"] is sentinel

    def test_randfall_idempotenz_zweiter_aufruf_geht_durch(self):
        # ChromaDB-Vertrag: get_or_create_collection ist idempotent. Unser
        # Wrapper darf da nichts kaputt machen – wir prüfen, dass er den
        # Aufruf einfach zweimal stellt, ohne eigene "schon angelegt"-Logik.
        client = MagicMock()
        embedding_function = MagicMock()

        rag.create_collection(client, "x", embedding_function)
        rag.create_collection(client, "x", embedding_function)

        assert client.get_or_create_collection.call_count == 2

    def test_fehlerfall_leerer_name(self):
        client = MagicMock()

        with pytest.raises(ValueError, match="darf nicht leer"):
            rag.create_collection(client, name="", embedding_function=MagicMock())

        client.get_or_create_collection.assert_not_called()

    def test_fehlerfall_whitespace_name(self):
        client = MagicMock()

        with pytest.raises(ValueError, match="darf nicht leer"):
            rag.create_collection(client, name="   ", embedding_function=MagicMock())

    def test_konstante_embedding_modell_ist_mehrsprachig(self):
        # Regression: schützt gegen versehentliches Zurückwechseln auf das
        # englisch-zentrierte Default-Modell. Die Wahl wurde explizit so
        # getroffen.
        assert "multilingual" in rag.EMBEDDING_MODELL


# ---------------------------------------------------------------------------
# index_chunks
# ---------------------------------------------------------------------------


class TestIndexChunks:
    def test_normalfall_baut_drei_parallele_listen(self):
        collection = MagicMock()
        chunks = [
            {"id": "a.txt#0", "quelle": "a.txt", "inhalt": "Text A0"},
            {"id": "a.txt#1", "quelle": "a.txt", "inhalt": "Text A1"},
            {"id": "b.txt#0", "quelle": "b.txt", "inhalt": "Text B0"},
        ]

        anzahl = rag.index_chunks(collection, chunks)

        assert anzahl == 3
        collection.add.assert_called_once_with(
            ids=["a.txt#0", "a.txt#1", "b.txt#0"],
            documents=["Text A0", "Text A1", "Text B0"],
            metadatas=[
                {"quelle": "a.txt"},
                {"quelle": "a.txt"},
                {"quelle": "b.txt"},
            ],
        )

    def test_normalfall_quelle_landet_in_metadaten_nicht_in_id_geparst(self):
        # Verteidigt das Designprinzip: die Quelle ist ein eigenes Feld in den
        # Metadaten. Wenn jemand das später "wegoptimieren" will, schlägt
        # dieser Test an.
        collection = MagicMock()
        chunks = [{"id": "doc#0", "quelle": "doc", "inhalt": "..."}]

        rag.index_chunks(collection, chunks)

        kwargs = collection.add.call_args.kwargs
        assert kwargs["metadatas"] == [{"quelle": "doc"}]

    def test_randfall_leere_liste_ruft_add_nicht_auf(self):
        # ChromaDB würde bei .add() mit leeren Listen mit einer kryptischen
        # Meldung abbrechen – wir fangen das vorher ab.
        collection = MagicMock()

        anzahl = rag.index_chunks(collection, [])

        assert anzahl == 0
        collection.add.assert_not_called()

    def test_fehlerfall_chunk_ohne_pflichtschluessel(self):
        collection = MagicMock()
        chunks = [{"id": "a#0", "quelle": "a", "inhalt": "ok"}, {"id": "b#0"}]

        with pytest.raises(ValueError, match="id.*quelle.*inhalt"):
            rag.index_chunks(collection, chunks)

        # Kritisch: kein partielles Schreiben. Auch der erste, gültige Chunk
        # darf nicht im Index landen, sonst hätten wir einen halb gefüllten
        # Zustand, der später schwer zu erklären ist.
        collection.add.assert_not_called()

    def test_fehlerfall_komplett_leeres_dict(self):
        collection = MagicMock()

        with pytest.raises(ValueError, match="id.*quelle.*inhalt"):
            rag.index_chunks(collection, [{}])

        collection.add.assert_not_called()


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


def _query_result(ids, documents, metadatas, distances):
    """Baut das ChromaDB-Query-Antwortformat (Listen-von-Listen) für Tests."""
    return {
        "ids": [ids],
        "documents": [documents],
        "metadatas": [metadatas],
        "distances": [distances],
    }


class TestSearch:
    def test_normalfall_flacht_chromadb_format_ab(self):
        collection = MagicMock()
        collection.query.return_value = _query_result(
            ids=["a.txt#0", "b.txt#1"],
            documents=["Erster Treffer", "Zweiter Treffer"],
            metadatas=[{"quelle": "a.txt"}, {"quelle": "b.txt"}],
            distances=[0.12, 0.45],
        )

        treffer = rag.search(collection, "Was steht zu Hotels?", n_results=2)

        assert treffer == [
            {
                "id": "a.txt#0",
                "quelle": "a.txt",
                "inhalt": "Erster Treffer",
                "distanz": 0.12,
            },
            {
                "id": "b.txt#1",
                "quelle": "b.txt",
                "inhalt": "Zweiter Treffer",
                "distanz": 0.45,
            },
        ]

    def test_normalfall_query_wird_korrekt_aufgerufen(self):
        collection = MagicMock()
        collection.query.return_value = _query_result([], [], [], [])

        rag.search(collection, "meine Frage", n_results=7)

        collection.query.assert_called_once_with(
            query_texts=["meine Frage"], n_results=7
        )

    def test_normalfall_default_n_results(self):
        collection = MagicMock()
        collection.query.return_value = _query_result([], [], [], [])

        rag.search(collection, "frage")

        kwargs = collection.query.call_args.kwargs
        assert kwargs["n_results"] == rag.DEFAULT_N_RESULTS

    def test_randfall_keine_treffer(self):
        # Collection leer oder nichts Ähnliches gefunden – ChromaDB liefert
        # leere Innen-Listen, wir liefern eine leere Liste.
        collection = MagicMock()
        collection.query.return_value = _query_result([], [], [], [])

        assert rag.search(collection, "irgendwas") == []

    def test_randfall_metadata_ohne_quelle_wird_zu_leerem_string(self):
        # Defensive: falls jemand mal Metadaten ohne 'quelle' indiziert hat
        # (z. B. fremde Daten), soll search nicht abstürzen, sondern eine
        # leere Quelle liefern.
        collection = MagicMock()
        collection.query.return_value = _query_result(
            ids=["x"], documents=["text"], metadatas=[{}], distances=[0.5]
        )

        treffer = rag.search(collection, "frage")

        assert treffer[0]["quelle"] == ""

    def test_fehlerfall_leere_frage(self):
        collection = MagicMock()

        with pytest.raises(ValueError, match="darf nicht leer"):
            rag.search(collection, "")

        collection.query.assert_not_called()

    def test_fehlerfall_whitespace_frage(self):
        collection = MagicMock()

        with pytest.raises(ValueError, match="darf nicht leer"):
            rag.search(collection, "   \n  ")

    def test_fehlerfall_n_results_null(self):
        collection = MagicMock()

        with pytest.raises(ValueError, match="muss positiv"):
            rag.search(collection, "frage", n_results=0)

    def test_fehlerfall_n_results_negativ(self):
        collection = MagicMock()

        with pytest.raises(ValueError, match="muss positiv"):
            rag.search(collection, "frage", n_results=-3)


# ---------------------------------------------------------------------------
# format_context
# ---------------------------------------------------------------------------


class TestFormatContext:
    def test_normalfall_baut_xml_block_mit_quellen_attribut(self):
        treffer = [
            {
                "id": "a.txt#0",
                "quelle": "reise.txt",
                "inhalt": "Bei Dienstreisen sind Hotels bis vier Sterne erlaubt.",
                "distanz": 0.12,
            },
            {
                "id": "b.txt#0",
                "quelle": "passwort.txt",
                "inhalt": "Passwörter müssen mindestens zwölf Zeichen haben.",
                "distanz": 0.34,
            },
        ]

        result = rag.format_context(treffer)

        erwartet = (
            "<kontext>\n"
            '<chunk quelle="reise.txt">\n'
            "Bei Dienstreisen sind Hotels bis vier Sterne erlaubt.\n"
            "</chunk>\n"
            '<chunk quelle="passwort.txt">\n'
            "Passwörter müssen mindestens zwölf Zeichen haben.\n"
            "</chunk>\n"
            "</kontext>"
        )
        assert result == erwartet

    def test_normalfall_einzelner_treffer(self):
        treffer = [{"quelle": "x.txt", "inhalt": "Solo-Inhalt"}]

        result = rag.format_context(treffer)

        assert result == (
            "<kontext>\n"
            '<chunk quelle="x.txt">\n'
            "Solo-Inhalt\n"
            "</chunk>\n"
            "</kontext>"
        )

    def test_normalfall_reihenfolge_bleibt_erhalten(self):
        # Wichtig: search liefert nach Distanz sortiert. format_context darf
        # diese Reihenfolge nicht durcheinander bringen, sonst sieht Claude
        # den schwächsten Treffer zuerst.
        treffer = [
            {"quelle": "a", "inhalt": "erst"},
            {"quelle": "b", "inhalt": "zweit"},
            {"quelle": "c", "inhalt": "dritt"},
        ]

        result = rag.format_context(treffer)

        assert result.index("erst") < result.index("zweit") < result.index("dritt")

    def test_randfall_leere_liste_gibt_leeren_string(self):
        # Bewusst kein "Keine Treffer"-Hinweis – das ist Aufgabe des Aufrufers.
        # Wir wollen format_context als reine Format-Funktion halten.
        assert rag.format_context([]) == ""

    def test_randfall_zusatzfelder_werden_ignoriert(self):
        # Treffer aus search() enthalten 'id' und 'distanz'. Die brauchen wir
        # in der XML-Form nicht – sie wären für Claude nur Rauschen.
        treffer = [
            {
                "id": "a.txt#0",
                "quelle": "a.txt",
                "inhalt": "Inhalt",
                "distanz": 0.5,
            }
        ]

        result = rag.format_context(treffer)

        assert "0.5" not in result
        assert "a.txt#0" not in result

    def test_fehlerfall_treffer_ohne_quelle(self):
        with pytest.raises(ValueError, match="quelle.*inhalt"):
            rag.format_context([{"inhalt": "text"}])

    def test_fehlerfall_treffer_ohne_inhalt(self):
        with pytest.raises(ValueError, match="quelle.*inhalt"):
            rag.format_context([{"quelle": "a.txt"}])


# ---------------------------------------------------------------------------
# End-to-End-Test mit echtem Embedding-Modell.
#
# Standardmäßig übersprungen, weil das Modell beim ersten Lauf einen ~120 MB
# Download und mehrere Sekunden zum Initialisieren braucht. Aktivieren mit
# Umgebungsvariable: ``RUN_E2E_TESTS=1 pytest tests/test_rag.py``. Sinnvoll
# nach Code-Änderungen in rag.py oder vor dem Code-Review.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("RUN_E2E_TESTS") != "1",
    reason="E2E-Test mit echtem Embedding-Modell; aktivieren mit RUN_E2E_TESTS=1",
)
def test_e2e_index_und_suche_finden_thematisch_passenden_chunk():  # pragma: no cover
    """Echter Round-Trip: indizieren, dann suchen, korrekten Treffer prüfen."""
    import chromadb

    # In-Memory-Client, damit data/chroma/ unangetastet bleibt.
    client = chromadb.EphemeralClient()
    collection = rag.create_collection(client, name="e2e_test")

    chunks = [
        {
            "id": "reise.txt#0",
            "quelle": "reise.txt",
            "inhalt": "Bei Dienstreisen sind Hotels bis maximal vier Sterne erlaubt.",
        },
        {
            "id": "passwort.txt#0",
            "quelle": "passwort.txt",
            "inhalt": "Passwörter müssen mindestens zwölf Zeichen lang sein.",
        },
        {
            "id": "ueberstunden.txt#0",
            "quelle": "ueberstunden.txt",
            "inhalt": "Überstunden werden im Folgemonat in Zeitausgleich umgewandelt.",
        },
    ]
    rag.index_chunks(collection, chunks)

    treffer = rag.search(collection, "Welche Hotelkategorie darf ich buchen?", n_results=1)

    # Der bestmögliche Treffer muss inhaltlich mit Hotels zu tun haben.
    assert treffer[0]["quelle"] == "reise.txt"

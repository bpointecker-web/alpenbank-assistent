"""Retrieval-Evaluation: naives Dense-only-Retrieval vs. Hybrid+Reranking.

Vergleicht beide Retrieval-Pipelines auf dem Golden-Set
(``eval/golden_set.py``) anhand von Hit-Rate@5 und MRR (Mean Reciprocal
Rank) – belegt mit Zahlen, was Stage 2.4 (Hybrid-Search) und 2.5
(Reranking) an Retrieval-Qualität bringen. Beide Pipelines laufen gegen
denselben Index (gleiche Chunks) – der einzige Unterschied ist die
Retrieval-Methode, damit der Vergleich genau diese Variable isoliert.

Braucht den echten Index (``data/chroma/``) und lädt beim ersten Lauf
den Cross-Encoder (~200 MB, siehe ``rag.RERANKER_MODELL``).

Aufruf aus dem Projekt-Root:
    .venv/Scripts/python.exe eval/run_eval.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Projekt-Root in den Importpfad aufnehmen, damit "from src import ..."
# auch beim direkten Skript-Aufruf funktioniert (analog zu rag_index.py).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chromadb  # noqa: E402

from eval.golden_set import GOLDEN_SET  # noqa: E402
from eval.metrics import hit_at_k, quellen_rangfolge, reciprocal_rank  # noqa: E402
from src import rag  # noqa: E402

CHROMA_PATH = Path("data/chroma")
REPORT_PATH = Path("docs/eval_report.md")

# Wie viele Top-Quellen für Hit-Rate@K zählen. 5 = DEFAULT_N_RESULTS,
# also die Anzahl Treffer, die Claude tatsächlich als Kontext bekommt.
K = 5


def naive_quellen(collection: Any, frage: str) -> list[str]:
    """Naives Retrieval: nur Dense-Suche, kein Hybrid, kein Reranking.

    Entspricht dem Stand vor Stage 2.4/2.5 – Vergleichsbasis für den
    Hybrid+Reranking-Pfad.
    """
    treffer = rag.search(collection, frage, n_results=K)
    return quellen_rangfolge(treffer)


def hybrid_rerank_quellen(
    collection: Any, bm25_index: rag.Bm25Index, reranker: Any, frage: str
) -> list[str]:
    """Aktuelle Produktions-Pipeline: Hybrid-Vorauswahl + Reranking.

    Identische Komposition wie ``agent._execute_dokumenten_suche``.
    """
    kandidaten = rag.hybrid_search(
        collection, bm25_index, frage, n_results=rag.RERANK_CANDIDATE_POOL
    )
    treffer = rag.rerank(frage, kandidaten, reranker, top_n=K)
    return quellen_rangfolge(treffer)


def bewerte(quellen: list[str], erwartete_quelle: str) -> dict[str, Any]:
    """Berechnet Hit@K und Reciprocal Rank für eine Frage."""
    return {
        "hit": hit_at_k(quellen, erwartete_quelle, K),
        "rr": reciprocal_rank(quellen, erwartete_quelle),
    }


def main() -> None:
    if not CHROMA_PATH.exists():
        raise SystemExit(
            f"ChromaDB-Pfad {CHROMA_PATH} existiert nicht. "
            "Bitte zuerst `python scripts/rag_index.py` ausführen."
        )

    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    collection = rag.create_collection(client, name=rag.COLLECTION_NAME)
    bm25_index = rag.build_bm25_index(collection)
    reranker = rag.get_default_reranker()

    zeilen_details: list[dict[str, Any]] = []
    for eintrag in GOLDEN_SET:
        naiv = bewerte(naive_quellen(collection, eintrag.frage), eintrag.erwartete_quelle)
        hybrid = bewerte(
            hybrid_rerank_quellen(collection, bm25_index, reranker, eintrag.frage),
            eintrag.erwartete_quelle,
        )
        zeilen_details.append(
            {
                "frage": eintrag.frage,
                "erwartete_quelle": eintrag.erwartete_quelle,
                "naiv": naiv,
                "hybrid": hybrid,
            }
        )
        print(f"[{len(zeilen_details)}/{len(GOLDEN_SET)}] {eintrag.frage}")

    anzahl = len(zeilen_details)
    naiv_hit_rate = sum(z["naiv"]["hit"] for z in zeilen_details) / anzahl
    naiv_mrr = sum(z["naiv"]["rr"] for z in zeilen_details) / anzahl
    hybrid_hit_rate = sum(z["hybrid"]["hit"] for z in zeilen_details) / anzahl
    hybrid_mrr = sum(z["hybrid"]["rr"] for z in zeilen_details) / anzahl

    print(f"\n{'Pipeline':<22} {'Hit-Rate@' + str(K):<12} {'MRR':<8}")
    print("-" * 44)
    print(f"{'naiv (Dense-only)':<22} {naiv_hit_rate:<12.0%} {naiv_mrr:<8.3f}")
    print(f"{'Hybrid + Reranking':<22} {hybrid_hit_rate:<12.0%} {hybrid_mrr:<8.3f}")

    bericht = [
        "# Retrieval-Evaluation: naiv vs. Hybrid+Reranking",
        "",
        f"Golden-Set: {anzahl} Fragen mit bekanntem Ziel-Dokument "
        "(siehe `eval/golden_set.py`). Metrik: Hit-Rate@{k} (Anteil Fragen, "
        "bei denen das richtige Dokument unter den Top-{k} Quellen ist) "
        "und MRR (Mean Reciprocal Rank, 1,0 = richtiges Dokument immer auf "
        "Platz 1). Beide Pipelines laufen gegen denselben Index – "
        "einziger Unterschied ist die Retrieval-Methode.".format(k=K),
        "",
        f"| Pipeline | Hit-Rate@{K} | MRR |",
        "|---|---|---|",
        f"| naiv (Dense-only) | {naiv_hit_rate:.0%} | {naiv_mrr:.3f} |",
        f"| Hybrid + Reranking | {hybrid_hit_rate:.0%} | {hybrid_mrr:.3f} |",
        "",
        "## Details pro Frage",
        "",
        "| Frage | Erwartete Quelle | naiv Treffer? | naiv RR | "
        "Hybrid+Rerank Treffer? | Hybrid+Rerank RR |",
        "|---|---|---|---|---|---|",
    ]
    for z in zeilen_details:
        naiv_symbol = "✅" if z["naiv"]["hit"] else "❌"
        hybrid_symbol = "✅" if z["hybrid"]["hit"] else "❌"
        bericht.append(
            f"| {z['frage']} | {z['erwartete_quelle']} | "
            f"{naiv_symbol} | {z['naiv']['rr']:.2f} | "
            f"{hybrid_symbol} | {z['hybrid']['rr']:.2f} |"
        )

    bericht.extend(
        [
            "",
            "## Hinweis zur Aussagekraft",
            "",
            f"Golden-Set mit {anzahl} Fragen ist bewusst klein (6 Dokumente "
            "Corpus) – ein einzelner Ausreißer verschiebt den Mittelwert "
            "spürbar. Auf diesem winzigen, thematisch klar getrennten "
            "Corpus liefert bereits naives Dense-Retrieval nahezu perfekte "
            "Ergebnisse; der publizierte Vorteil von Hybrid-Search + "
            "Reranking (15–40 % laut Literatur, siehe Projekt-Review) "
            "zeigt sich empirisch erst bei größeren, mehrdeutigeren Corpora "
            "mit vielen Near-Miss-Kandidaten – nicht notwendigerweise auf "
            "sechs klar unterscheidbaren Dokumenten. Diese Auswertung "
            "beweist also nicht 'Hybrid+Reranking ist hier besser', "
            "sondern macht Retrieval-Qualität überhaupt erstmals messbar "
            "und zeigt ehrlich, wo die Methode bei diesem Corpus (noch) "
            "keinen Unterschied macht bzw. auf einer Einzelfrage sogar "
            "schwächer abschneidet.",
        ]
    )

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(bericht) + "\n", encoding="utf-8")
    print(f"\nReport geschrieben nach {REPORT_PATH}")


if __name__ == "__main__":
    main()

"""Unit-Tests für eval/metrics.py.

Pro Funktion mindestens drei Fälle (Normalfall, Randfall, Fehlerfall)
gemäß CLAUDE.md.
"""

from __future__ import annotations

import pytest

from eval import metrics


# ---------------------------------------------------------------------------
# quellen_rangfolge
# ---------------------------------------------------------------------------


class TestQuellenRangfolge:
    def test_normalfall_dedupliziert_mehrfache_chunks_desselben_dokuments(self):
        treffer = [
            {"quelle": "a.txt", "inhalt": "..."},
            {"quelle": "a.txt", "inhalt": "..."},
            {"quelle": "b.txt", "inhalt": "..."},
        ]

        assert metrics.quellen_rangfolge(treffer) == ["a.txt", "b.txt"]

    def test_normalfall_erhaelt_reihenfolge_des_ersten_vorkommens(self):
        treffer = [
            {"quelle": "b.txt"},
            {"quelle": "a.txt"},
            {"quelle": "b.txt"},
        ]

        assert metrics.quellen_rangfolge(treffer) == ["b.txt", "a.txt"]

    def test_randfall_leere_trefferliste_gibt_leere_liste(self):
        assert metrics.quellen_rangfolge([]) == []


# ---------------------------------------------------------------------------
# hit_at_k
# ---------------------------------------------------------------------------


class TestHitAtK:
    def test_normalfall_quelle_unter_den_top_k(self):
        assert metrics.hit_at_k(["a.txt", "b.txt", "c.txt"], "b.txt", k=3) is True

    def test_normalfall_quelle_ausserhalb_der_top_k(self):
        assert metrics.hit_at_k(["a.txt", "b.txt", "c.txt"], "c.txt", k=2) is False

    def test_randfall_quelle_gar_nicht_vorhanden(self):
        assert metrics.hit_at_k(["a.txt"], "nicht_da.txt", k=5) is False

    def test_randfall_leere_liste(self):
        assert metrics.hit_at_k([], "a.txt", k=5) is False

    def test_fehlerfall_k_nicht_positiv(self):
        with pytest.raises(ValueError, match="k muss positiv sein"):
            metrics.hit_at_k(["a.txt"], "a.txt", k=0)


# ---------------------------------------------------------------------------
# reciprocal_rank
# ---------------------------------------------------------------------------


class TestReciprocalRank:
    def test_normalfall_quelle_auf_platz_eins(self):
        assert metrics.reciprocal_rank(["a.txt", "b.txt"], "a.txt") == 1.0

    def test_normalfall_quelle_auf_platz_drei(self):
        assert metrics.reciprocal_rank(
            ["a.txt", "b.txt", "c.txt"], "c.txt"
        ) == pytest.approx(1 / 3)

    def test_randfall_quelle_nicht_gefunden_gibt_null(self):
        assert metrics.reciprocal_rank(["a.txt"], "nicht_da.txt") == 0.0

    def test_randfall_leere_liste_gibt_null(self):
        assert metrics.reciprocal_rank([], "a.txt") == 0.0

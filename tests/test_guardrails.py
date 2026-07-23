"""Unit-Tests für src/guardrails.py.

Pro Funktion mindestens drei Fälle (Normalfall, Randfall, Fehlerfall)
gemäß CLAUDE.md.
"""

from __future__ import annotations

import pytest

from src import guardrails


# ---------------------------------------------------------------------------
# pruefe_nutzereingabe
# ---------------------------------------------------------------------------


class TestPruefeNutzereingabe:
    def test_normalfall_valide_frage_wirft_nichts(self):
        # Kein Fehler = Erfolg. Der Test besteht, wenn nichts geworfen wird.
        guardrails.pruefe_nutzereingabe("Welche Hotelkategorie darf ich buchen?")

    def test_normalfall_frage_mit_umlauten_und_satzzeichen(self):
        guardrails.pruefe_nutzereingabe(
            "Wie hoch sind die Überstundenzuschläge – 25% oder 50%?"
        )

    def test_randfall_frage_genau_an_der_laengengrenze(self):
        frage = "x" * guardrails.MAX_FRAGE_LAENGE
        guardrails.pruefe_nutzereingabe(frage)

    def test_randfall_leere_frage_wird_nicht_von_dieser_funktion_abgefangen(self):
        # Leere-Frage-Validierung ist Sache von agent.answer_question
        # (dort bereits abgesichert) - guardrails prüft nur Länge/
        # Steuerzeichen, keine inhaltliche Leere.
        guardrails.pruefe_nutzereingabe("")

    def test_fehlerfall_frage_zu_lang(self):
        frage = "x" * (guardrails.MAX_FRAGE_LAENGE + 1)

        with pytest.raises(guardrails.EingabeAbgelehnt, match="zu lang"):
            guardrails.pruefe_nutzereingabe(frage)

    def test_fehlerfall_steuerzeichen_im_text(self):
        frage = "Normale Frage\x00mit eingebettetem Nullbyte"

        with pytest.raises(guardrails.EingabeAbgelehnt, match="Steuerzeichen"):
            guardrails.pruefe_nutzereingabe(frage)

    def test_fehlerfall_ist_ein_value_error(self):
        # EingabeAbgelehnt muss ValueError sein, damit generischer
        # Fehler-Handling-Code (falls vorhanden) sie trotzdem fängt.
        with pytest.raises(ValueError):
            guardrails.pruefe_nutzereingabe("x" * (guardrails.MAX_FRAGE_LAENGE + 1))


# ---------------------------------------------------------------------------
# budget_ueberschritten
# ---------------------------------------------------------------------------


class TestBudgetUeberschritten:
    def test_normalfall_unter_budget(self):
        assert guardrails.budget_ueberschritten(1000, 50_000) is False

    def test_normalfall_ueber_budget(self):
        assert guardrails.budget_ueberschritten(60_000, 50_000) is True

    def test_randfall_genau_am_budget(self):
        # >=, nicht > : ein Verbrauch, der das Budget exakt erreicht,
        # zählt bereits als ausgeschöpft - die nächste Frage würde es
        # sonst überschreiten, ohne vorher gewarnt zu haben.
        assert guardrails.budget_ueberschritten(50_000, 50_000) is True

    def test_randfall_null_verbrauch(self):
        assert guardrails.budget_ueberschritten(0, 50_000) is False

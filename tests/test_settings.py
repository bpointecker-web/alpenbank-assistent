"""Unit-Tests für src/settings.py.

Pro Funktion mindestens drei Fälle (Normalfall, Randfall, Fehlerfall)
gemäß CLAUDE.md.
"""

from __future__ import annotations

import pytest

from src import agent, rag, settings


# ---------------------------------------------------------------------------
# load_settings
# ---------------------------------------------------------------------------


class TestLoadSettings:
    def test_normalfall_leere_umgebung_liefert_ist_zustand_defaults(self):
        result = settings.load_settings({})

        assert result == settings.Settings(
            woerter_pro_chunk=150,
            wort_overlap=30,
            n_results=5,
            model="claude-sonnet-4-6",
            max_tokens=2048,
            max_iterations=5,
            session_token_budget=50_000,
            query_rewriting=True,
            query_variants=3,
        )

    def test_normalfall_teil_override_laesst_rest_beim_default(self):
        result = settings.load_settings({"ALPENBANK_MAX_TOKENS": "2048"})

        assert result.max_tokens == 2048
        assert result.woerter_pro_chunk == 150
        assert result.model == "claude-sonnet-4-6"

    def test_normalfall_alle_werte_ueberschrieben(self):
        env = {
            "ALPENBANK_WOERTER_PRO_CHUNK": "150",
            "ALPENBANK_WORT_OVERLAP": "30",
            "ALPENBANK_N_RESULTS": "10",
            "ALPENBANK_MODEL": "claude-opus-4-8",
            "ALPENBANK_MAX_TOKENS": "2048",
            "ALPENBANK_MAX_ITERATIONS": "8",
            "ALPENBANK_SESSION_TOKEN_BUDGET": "100000",
            "ALPENBANK_QUERY_REWRITING": "0",
            "ALPENBANK_QUERY_VARIANTS": "5",
        }

        result = settings.load_settings(env)

        assert result == settings.Settings(
            woerter_pro_chunk=150,
            wort_overlap=30,
            n_results=10,
            model="claude-opus-4-8",
            max_tokens=2048,
            max_iterations=8,
            session_token_budget=100_000,
            query_rewriting=False,
            query_variants=5,
        )

    def test_randfall_none_nutzt_echte_prozessumgebung(self, monkeypatch):
        for key in (
            "ALPENBANK_WOERTER_PRO_CHUNK",
            "ALPENBANK_WORT_OVERLAP",
            "ALPENBANK_N_RESULTS",
            "ALPENBANK_MODEL",
            "ALPENBANK_MAX_TOKENS",
            "ALPENBANK_MAX_ITERATIONS",
            "ALPENBANK_SESSION_TOKEN_BUDGET",
        ):
            monkeypatch.delenv(key, raising=False)

        result = settings.load_settings(None)

        assert result.woerter_pro_chunk == 150

    def test_fehlerfall_nicht_numerischer_wert(self):
        with pytest.raises(ValueError, match="gültige Ganzzahl"):
            settings.load_settings({"ALPENBANK_MAX_TOKENS": "abc"})

    def test_fehlerfall_negativer_wert(self):
        with pytest.raises(ValueError, match="muss positiv sein"):
            settings.load_settings({"ALPENBANK_N_RESULTS": "-1"})

    def test_fehlerfall_null_wert(self):
        with pytest.raises(ValueError, match="muss positiv sein"):
            settings.load_settings({"ALPENBANK_MAX_ITERATIONS": "0"})

    def test_fehlerfall_overlap_groesser_gleich_chunk(self):
        env = {
            "ALPENBANK_WOERTER_PRO_CHUNK": "100",
            "ALPENBANK_WORT_OVERLAP": "100",
        }

        with pytest.raises(ValueError, match="muss kleiner sein"):
            settings.load_settings(env)

    def test_fehlerfall_leeres_model(self):
        with pytest.raises(ValueError, match="darf nicht leer sein"):
            settings.load_settings({"ALPENBANK_MODEL": "   "})

    def test_normalfall_query_rewriting_default_an(self):
        result = settings.load_settings({})

        assert result.query_rewriting is True
        assert result.query_variants == 3

    def test_normalfall_query_rewriting_abschaltbar(self):
        result = settings.load_settings({"ALPENBANK_QUERY_REWRITING": "false"})

        assert result.query_rewriting is False

    def test_randfall_query_rewriting_akzeptiert_diverse_schreibweisen(self):
        for wahr in ("1", "true", "TRUE", "yes", "on"):
            assert (
                settings.load_settings({"ALPENBANK_QUERY_REWRITING": wahr}).query_rewriting
                is True
            )
        for falsch in ("0", "false", "No", "off"):
            assert (
                settings.load_settings({"ALPENBANK_QUERY_REWRITING": falsch}).query_rewriting
                is False
            )

    def test_fehlerfall_query_rewriting_unsinniger_wert(self):
        with pytest.raises(ValueError, match="gültiger Wahrheitswert"):
            settings.load_settings({"ALPENBANK_QUERY_REWRITING": "vielleicht"})

    def test_fehlerfall_query_variants_nicht_positiv(self):
        with pytest.raises(ValueError, match="muss positiv sein"):
            settings.load_settings({"ALPENBANK_QUERY_VARIANTS": "0"})


# ---------------------------------------------------------------------------
# Integration: rag.py/agent.py müssen ihre Konstanten aus SETTINGS beziehen
# ---------------------------------------------------------------------------


class TestModulkonstantenStimmenMitSettingsUeberein:
    def test_normalfall_rag_konstanten_stammen_aus_settings(self):
        assert rag.WOERTER_PRO_CHUNK == settings.SETTINGS.woerter_pro_chunk
        assert rag.WORT_OVERLAP == settings.SETTINGS.wort_overlap
        assert rag.DEFAULT_N_RESULTS == settings.SETTINGS.n_results

    def test_normalfall_agent_konstanten_stammen_aus_settings(self):
        assert agent.MODEL == settings.SETTINGS.model
        assert agent.MAX_TOKENS == settings.SETTINGS.max_tokens
        assert agent.DEFAULT_MAX_ITERATIONS == settings.SETTINGS.max_iterations

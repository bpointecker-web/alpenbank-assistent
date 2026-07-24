"""Unit-Tests für src/demo.py.

Pro Funktion mindestens drei Fälle (Normalfall, Randfall, Fehlerfall)
gemäß CLAUDE.md.
"""

from __future__ import annotations

import json

import pytest

from src import agent, demo


# ---------------------------------------------------------------------------
# normalize_frage
# ---------------------------------------------------------------------------


class TestNormalizeFrage:
    def test_normalfall_gross_klein_und_leerzeichen_werden_vereinheitlicht(self):
        assert demo.normalize_frage("  Wie Hoch   waren  die Erträge?  ") == (
            "wie hoch waren die erträge?"
        )

    def test_randfall_bereits_normalisierte_frage_bleibt_gleich(self):
        frage = "lösch alle buchungen!"
        assert demo.normalize_frage(frage) == frage

    def test_randfall_tabs_und_zeilenumbrueche_zaehlen_als_leerzeichen(self):
        assert demo.normalize_frage("Wie\thoch\nwaren sie?") == "wie hoch waren sie?"


# ---------------------------------------------------------------------------
# serialize_antwort / deserialize_antwort (Roundtrip)
# ---------------------------------------------------------------------------


class TestSerializeDeserializeAntwort:
    def test_normalfall_roundtrip_erhaelt_alle_felder(self):
        antwort = agent.AgentAntwort(
            text="Die Erträge betrugen 123.456,78 €.",
            traces=[
                agent.ToolCallTrace(
                    name="datenbank_abfrage",
                    tool_input={"sql": "SELECT 1"},
                    tool_use_id="toolu_123",
                    ergebnis=agent.ToolErgebnis(
                        text="| a |\n| - |\n| 1 |",
                        is_error=False,
                        details={"sql": "SELECT 1", "tabelle": "| a |\n| - |\n| 1 |"},
                    ),
                )
            ],
            iterations_used=1,
        )

        serialisiert = demo.serialize_antwort(antwort)
        # Muss JSON-fest sein - das ist der eigentliche Zweck der Funktion.
        rundgereist = json.loads(json.dumps(serialisiert, ensure_ascii=False))
        rekonstruiert = demo.deserialize_antwort(rundgereist)

        assert rekonstruiert.text == antwort.text
        assert rekonstruiert.iterations_used == antwort.iterations_used
        assert len(rekonstruiert.traces) == 1
        assert rekonstruiert.traces[0].name == "datenbank_abfrage"
        assert rekonstruiert.traces[0].tool_input == {"sql": "SELECT 1"}
        assert rekonstruiert.traces[0].ergebnis.is_error is False
        assert rekonstruiert.traces[0].ergebnis.details == {
            "sql": "SELECT 1",
            "tabelle": "| a |\n| - |\n| 1 |",
        }

    def test_randfall_keine_tool_aufrufe(self):
        antwort = agent.AgentAntwort(text="Direkte Antwort.", traces=[], iterations_used=1)

        serialisiert = demo.serialize_antwort(antwort)
        rekonstruiert = demo.deserialize_antwort(serialisiert)

        assert serialisiert["traces"] == []
        assert rekonstruiert.traces == []

    def test_randfall_fehlerhafter_tool_aufruf_bleibt_erhalten(self):
        antwort = agent.AgentAntwort(
            text="Konnte nicht beantwortet werden.",
            traces=[
                agent.ToolCallTrace(
                    name="datenbank_abfrage",
                    tool_input={"sql": "DELETE FROM buchungen"},
                    tool_use_id="toolu_456",
                    ergebnis=agent.ToolErgebnis(
                        text="Fehler: Diese Abfrage wurde abgelehnt.",
                        is_error=True,
                        details={"sql": "DELETE FROM buchungen"},
                    ),
                )
            ],
            iterations_used=1,
        )

        rekonstruiert = demo.deserialize_antwort(demo.serialize_antwort(antwort))

        assert rekonstruiert.traces[0].ergebnis.is_error is True


# ---------------------------------------------------------------------------
# load_cache
# ---------------------------------------------------------------------------


class TestLoadCache:
    def test_normalfall_laedt_und_indiziert_nach_normalisierter_frage(self, tmp_path):
        cache_pfad = tmp_path / "demo_cache.json"
        cache_pfad.write_text(
            json.dumps(
                [{"frage": "  Wie Hoch waren die Erträge?  ", "text": "123 €", "iterations_used": 1, "traces": []}]
            ),
            encoding="utf-8",
        )

        cache = demo.load_cache(cache_pfad)

        assert "wie hoch waren die erträge?" in cache
        assert cache["wie hoch waren die erträge?"]["text"] == "123 €"

    def test_randfall_leere_liste_ergibt_leeres_dict(self, tmp_path):
        cache_pfad = tmp_path / "demo_cache.json"
        cache_pfad.write_text("[]", encoding="utf-8")

        assert demo.load_cache(cache_pfad) == {}

    def test_fehlerfall_nicht_existente_datei(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="existiert nicht"):
            demo.load_cache(tmp_path / "gibt_es_nicht.json")


# ---------------------------------------------------------------------------
# lookup
# ---------------------------------------------------------------------------


class TestLookup:
    def test_normalfall_findet_eintrag_unabhaengig_von_schreibweise(self):
        cache = {"wie hoch waren die erträge?": {"text": "123 €"}}

        assert demo.lookup(cache, "  WIE HOCH waren die Erträge?  ") == {"text": "123 €"}

    def test_randfall_kein_treffer_gibt_none(self):
        cache = {"wie hoch waren die erträge?": {"text": "123 €"}}

        assert demo.lookup(cache, "Eine ganz andere Frage") is None

    def test_randfall_leerer_cache_gibt_none(self):
        assert demo.lookup({}, "irgendeine Frage") is None


# ---------------------------------------------------------------------------
# simulate_streaming (Demo-Streaming, Stage 2.7)
# ---------------------------------------------------------------------------


class TestSimulateStreaming:
    @staticmethod
    def _antwort_mit_trace():
        return agent.AgentAntwort(
            text="Hallo",
            traces=[
                agent.ToolCallTrace(
                    name="dokumenten_suche",
                    tool_input={"frage": "x"},
                    tool_use_id="demo",
                    ergebnis=agent.ToolErgebnis(
                        text="ctx", is_error=False, details=[]
                    ),
                )
            ],
            iterations_used=1,
        )

    def test_normalfall_text_dann_trace_dann_done(self):
        antwort = self._antwort_mit_trace()

        events = list(
            demo.simulate_streaming(
                antwort, zeichen_pro_delta=2, verzoegerung=0, sleep=lambda s: None
            )
        )

        text = "".join(
            e.text for e in events if isinstance(e, agent.TextDelta)
        )
        assert text == "Hallo"
        assert any(isinstance(e, agent.ToolCallFinished) for e in events)
        assert isinstance(events[-1], agent.Done)
        assert events[-1].antwort is antwort

    def test_randfall_leerer_text_nur_done(self):
        antwort = agent.AgentAntwort(text="", traces=[], iterations_used=0)

        events = list(
            demo.simulate_streaming(antwort, verzoegerung=0, sleep=lambda s: None)
        )

        assert [type(e).__name__ for e in events] == ["Done"]

    def test_randfall_sleep_wird_pro_delta_aufgerufen(self):
        antwort = agent.AgentAntwort(text="abcd", traces=[], iterations_used=0)
        aufrufe = []

        list(
            demo.simulate_streaming(
                antwort,
                zeichen_pro_delta=2,
                verzoegerung=0.01,
                sleep=lambda s: aufrufe.append(s),
            )
        )

        # "abcd" bei 2 Zeichen/Delta -> 2 Deltas -> 2 sleep-Aufrufe.
        assert len(aufrufe) == 2

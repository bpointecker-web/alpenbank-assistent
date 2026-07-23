"""Unit-Tests für src/audit.py.

Pro Funktion mindestens drei Fälle (Normalfall, Randfall, Fehlerfall)
gemäß CLAUDE.md.
"""

from __future__ import annotations

import json

import pytest

from src import agent, audit


def _antwort(traces, iterations_used=1, input_tokens=100, output_tokens=50):
    return agent.AgentAntwort(
        text="Antworttext",
        traces=traces,
        iterations_used=iterations_used,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _trace(name, is_error, details):
    return agent.ToolCallTrace(
        name=name,
        tool_input={},
        tool_use_id="tu_001",
        ergebnis=agent.ToolErgebnis(text="...", is_error=is_error, details=details),
    )


# ---------------------------------------------------------------------------
# baue_audit_eintrag
# ---------------------------------------------------------------------------


class TestBaueAuditEintrag:
    def test_normalfall_sammelt_quellen_und_sql(self):
        traces = [
            _trace(
                "dokumenten_suche",
                False,
                [{"quelle": "reisekostenrichtlinie.txt", "inhalt": "..."}],
            ),
            _trace(
                "datenbank_abfrage",
                False,
                {"sql": "SELECT name FROM konten", "tabelle": "..."},
            ),
        ]

        eintrag = audit.baue_audit_eintrag("Frage?", _antwort(traces), "claude-sonnet-4-6")

        assert eintrag.quellen == ["reisekostenrichtlinie.txt"]
        assert eintrag.sql_statements == ["SELECT name FROM konten"]
        assert eintrag.modell == "claude-sonnet-4-6"
        assert eintrag.input_tokens == 100
        assert eintrag.output_tokens == 50
        assert len(eintrag.tool_aufrufe) == 2

    def test_normalfall_dedupliziert_mehrfache_quellen(self):
        traces = [
            _trace(
                "dokumenten_suche",
                False,
                [
                    {"quelle": "a.txt", "inhalt": "..."},
                    {"quelle": "a.txt", "inhalt": "..."},
                    {"quelle": "b.txt", "inhalt": "..."},
                ],
            )
        ]

        eintrag = audit.baue_audit_eintrag("Frage?", _antwort(traces), "modell")

        assert eintrag.quellen == ["a.txt", "b.txt"]

    def test_randfall_abgelehnter_sql_aufruf_wird_trotzdem_geloggt(self):
        # Ein abgelehnter Schreibversuch ist audit-relevant, kein Grund
        # zum Weglassen - im Gegenteil, das ist der Beleg, dass die
        # Whitelist gegriffen hat.
        traces = [
            _trace(
                "datenbank_abfrage",
                True,
                {"sql": "DELETE FROM buchungen"},
            )
        ]

        eintrag = audit.baue_audit_eintrag("Lösch alles!", _antwort(traces), "modell")

        assert eintrag.sql_statements == ["DELETE FROM buchungen"]
        assert eintrag.tool_aufrufe[0]["is_error"] is True

    def test_randfall_keine_tool_aufrufe(self):
        eintrag = audit.baue_audit_eintrag("Hallo", _antwort([]), "modell")

        assert eintrag.quellen == []
        assert eintrag.sql_statements == []
        assert eintrag.tool_aufrufe == []

    def test_normalfall_pii_in_der_frage_wird_redigiert(self):
        # Stage 4.5: die Nutzerfrage ist Freitext und koennte
        # versehentlich eingetippte PII enthalten - im Audit-Log darf
        # sie nicht im Klartext landen.
        frage = "Bitte antworte an kontakt@alpenbank.at"

        eintrag = audit.baue_audit_eintrag(frage, _antwort([]), "modell")

        assert "kontakt@alpenbank.at" not in eintrag.frage
        assert "[REDIGIERT: E-Mail]" in eintrag.frage

    def test_randfall_dokumenten_suche_ohne_details_bricht_nicht_ab(self):
        # Bei einem Eingabe-Fehler (z. B. leere Frage) ist details=None -
        # baue_audit_eintrag muss das tolerieren, nicht abstürzen.
        traces = [_trace("dokumenten_suche", True, None)]

        eintrag = audit.baue_audit_eintrag("Frage?", _antwort(traces), "modell")

        assert eintrag.quellen == []

    def test_normalfall_sammelt_guardrail_hinweise(self):
        # Spiegelt agent._execute_dokumenten_suche: Treffer, denen die
        # Injection-Heuristik ein "guardrail_hinweise"-Feld angehängt
        # hat, muessen im Audit-Eintrag landen.
        traces = [
            _trace(
                "dokumenten_suche",
                False,
                [
                    {
                        "quelle": "kundenkommunikation.txt",
                        "inhalt": "...",
                        "guardrail_hinweise": ["system:"],
                    }
                ],
            )
        ]

        eintrag = audit.baue_audit_eintrag("Frage?", _antwort(traces), "modell")

        assert len(eintrag.guardrail_hinweise) == 1
        assert "kundenkommunikation.txt" in eintrag.guardrail_hinweise[0]
        assert "system:" in eintrag.guardrail_hinweise[0]

    def test_randfall_keine_guardrail_hinweise_gibt_leere_liste(self):
        traces = [
            _trace(
                "dokumenten_suche",
                False,
                [{"quelle": "a.txt", "inhalt": "unauffällig"}],
            )
        ]

        eintrag = audit.baue_audit_eintrag("Frage?", _antwort(traces), "modell")

        assert eintrag.guardrail_hinweise == []


# ---------------------------------------------------------------------------
# log_audit_eintrag
# ---------------------------------------------------------------------------


class TestLogAuditEintrag:
    def test_normalfall_schreibt_valide_json_zeile(self, tmp_path):
        pfad = tmp_path / "audit_log.jsonl"
        eintrag = audit.baue_audit_eintrag("Frage?", _antwort([]), "modell")

        audit.log_audit_eintrag(eintrag, pfad)

        zeilen = pfad.read_text(encoding="utf-8").splitlines()
        assert len(zeilen) == 1
        geladen = json.loads(zeilen[0])
        assert geladen["frage"] == "Frage?"
        assert geladen["modell"] == "modell"

    def test_normalfall_mehrere_eintraege_werden_angehaengt(self, tmp_path):
        pfad = tmp_path / "audit_log.jsonl"
        audit.log_audit_eintrag(
            audit.baue_audit_eintrag("Erste Frage", _antwort([]), "modell"), pfad
        )
        audit.log_audit_eintrag(
            audit.baue_audit_eintrag("Zweite Frage", _antwort([]), "modell"), pfad
        )

        zeilen = pfad.read_text(encoding="utf-8").splitlines()
        assert len(zeilen) == 2
        assert json.loads(zeilen[0])["frage"] == "Erste Frage"
        assert json.loads(zeilen[1])["frage"] == "Zweite Frage"

    def test_randfall_uebergeordnetes_verzeichnis_wird_angelegt(self, tmp_path):
        pfad = tmp_path / "neuer_ordner" / "audit_log.jsonl"
        eintrag = audit.baue_audit_eintrag("Frage?", _antwort([]), "modell")

        audit.log_audit_eintrag(eintrag, pfad)

        assert pfad.exists()


# ---------------------------------------------------------------------------
# lies_audit_log
# ---------------------------------------------------------------------------


class TestLiesAuditLog:
    def test_normalfall_liest_alle_eintraege(self, tmp_path):
        pfad = tmp_path / "audit_log.jsonl"
        for i in range(3):
            audit.log_audit_eintrag(
                audit.baue_audit_eintrag(f"Frage {i}", _antwort([]), "modell"), pfad
            )

        eintraege = audit.lies_audit_log(pfad)

        assert len(eintraege) == 3
        assert eintraege[0]["frage"] == "Frage 0"

    def test_normalfall_limit_beschraenkt_auf_letzte_n(self, tmp_path):
        pfad = tmp_path / "audit_log.jsonl"
        for i in range(5):
            audit.log_audit_eintrag(
                audit.baue_audit_eintrag(f"Frage {i}", _antwort([]), "modell"), pfad
            )

        eintraege = audit.lies_audit_log(pfad, limit=2)

        assert [e["frage"] for e in eintraege] == ["Frage 3", "Frage 4"]

    def test_randfall_datei_existiert_nicht(self, tmp_path):
        assert audit.lies_audit_log(tmp_path / "gibt_es_nicht.jsonl") == []

    def test_randfall_leere_datei(self, tmp_path):
        pfad = tmp_path / "audit_log.jsonl"
        pfad.write_text("", encoding="utf-8")

        assert audit.lies_audit_log(pfad) == []


# ---------------------------------------------------------------------------
# session_zusammenfassung
# ---------------------------------------------------------------------------


class TestSessionZusammenfassung:
    def test_normalfall_zaehlt_fragen_und_sammelt_quellen(self):
        messages = [
            {"role": "user", "content": "Frage 1"},
            {
                "role": "assistant",
                "content": "Antwort 1",
                "traces": [
                    _trace(
                        "dokumenten_suche",
                        False,
                        [{"quelle": "a.txt", "inhalt": "..."}],
                    )
                ],
            },
            {"role": "user", "content": "Frage 2"},
            {
                "role": "assistant",
                "content": "Antwort 2",
                "traces": [
                    _trace(
                        "dokumenten_suche",
                        False,
                        [{"quelle": "b.txt", "inhalt": "..."}],
                    )
                ],
            },
        ]

        ergebnis = audit.session_zusammenfassung(messages)

        assert ergebnis["anzahl_fragen"] == 2
        assert ergebnis["quellen"] == ["a.txt", "b.txt"]
        assert ergebnis["guardrail_hinweise"] == []

    def test_normalfall_sammelt_guardrail_hinweise(self):
        messages = [
            {"role": "user", "content": "Frage"},
            {
                "role": "assistant",
                "content": "Antwort",
                "traces": [
                    _trace(
                        "dokumenten_suche",
                        False,
                        [
                            {
                                "quelle": "kundenkommunikation.txt",
                                "inhalt": "...",
                                "guardrail_hinweise": ["system:"],
                            }
                        ],
                    )
                ],
            },
        ]

        ergebnis = audit.session_zusammenfassung(messages)

        assert len(ergebnis["guardrail_hinweise"]) == 1
        assert "kundenkommunikation.txt" in ergebnis["guardrail_hinweise"][0]

    def test_normalfall_dedupliziert_quellen_ueber_mehrere_nachrichten(self):
        messages = [
            {
                "role": "assistant",
                "content": "A",
                "traces": [
                    _trace("dokumenten_suche", False, [{"quelle": "a.txt", "inhalt": "x"}])
                ],
            },
            {
                "role": "assistant",
                "content": "B",
                "traces": [
                    _trace("dokumenten_suche", False, [{"quelle": "a.txt", "inhalt": "y"}])
                ],
            },
        ]

        ergebnis = audit.session_zusammenfassung(messages)

        assert ergebnis["quellen"] == ["a.txt"]

    def test_randfall_leere_historie(self):
        ergebnis = audit.session_zusammenfassung([])

        assert ergebnis == {
            "anzahl_fragen": 0,
            "quellen": [],
            "guardrail_hinweise": [],
        }

    def test_randfall_nachrichten_ohne_traces_schluessel(self):
        # User-Nachrichten haben keinen "traces"-Schlüssel - darf nicht
        # zum Absturz führen.
        messages = [{"role": "user", "content": "Frage ohne Antwort noch"}]

        ergebnis = audit.session_zusammenfassung(messages)

        assert ergebnis["anzahl_fragen"] == 1
        assert ergebnis["quellen"] == []

    def test_randfall_datenbank_abfrage_traces_werden_ignoriert(self):
        messages = [
            {
                "role": "assistant",
                "content": "Antwort",
                "traces": [
                    _trace("datenbank_abfrage", False, {"sql": "SELECT 1", "tabelle": "..."})
                ],
            }
        ]

        ergebnis = audit.session_zusammenfassung(messages)

        assert ergebnis["quellen"] == []

    def test_robustheit_traces_als_dicts_statt_namedtuples(self):
        # Absicherung gegen die Streamlit-Cloud-Ursache (AttributeError im
        # Governance-Panel): liegen Traces aus irgendeinem Grund als dicts
        # statt agent.ToolCallTrace vor, muss die Auswertung trotzdem
        # funktionieren statt abzustürzen.
        messages = [
            {
                "role": "user",
                "content": "Frage",
            },
            {
                "role": "assistant",
                "content": "Antwort",
                "traces": [
                    {
                        "name": "dokumenten_suche",
                        "ergebnis": {
                            "details": [
                                {
                                    "quelle": "kundenkommunikation.txt",
                                    "inhalt": "...",
                                    "guardrail_hinweise": ["system:"],
                                }
                            ]
                        },
                    }
                ],
            },
        ]

        ergebnis = audit.session_zusammenfassung(messages)

        assert ergebnis["anzahl_fragen"] == 1
        assert ergebnis["quellen"] == ["kundenkommunikation.txt"]
        assert len(ergebnis["guardrail_hinweise"]) == 1

    def test_robustheit_nicht_dict_nachricht_wird_uebersprungen(self):
        # Eine Nachricht, die kein dict ist (z. B. durch beschädigten
        # Session-State), darf die Auswertung nicht crashen - der erste
        # Zugriff war frueher msg.get(...) und wuerde bei einem String
        # eine AttributeError werfen.
        messages = [
            "kaputte nachricht als string",
            {"role": "user", "content": "echte Frage"},
        ]

        ergebnis = audit.session_zusammenfassung(messages)

        assert ergebnis["anzahl_fragen"] == 1

    def test_robustheit_trace_ohne_details_und_ergebnis(self):
        # Trace ohne ergebnis / mit ergebnis=None darf nicht crashen.
        messages = [
            {
                "role": "assistant",
                "content": "Antwort",
                "traces": [{"name": "dokumenten_suche", "ergebnis": None}],
            }
        ]

        ergebnis = audit.session_zusammenfassung(messages)

        assert ergebnis["quellen"] == []

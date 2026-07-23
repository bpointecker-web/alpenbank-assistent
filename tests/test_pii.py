"""Unit-Tests für src/pii.py.

Pro Funktion mindestens drei Fälle (Normalfall, Randfall, Fehlerfall)
gemäß CLAUDE.md. "Fehlerfall" interpretieren wir hier als Grenzfälle,
die leicht zu False Positives/Negatives führen könnten – die Funktionen
selbst werfen keine Exceptions.
"""

from __future__ import annotations

from src import pii


# ---------------------------------------------------------------------------
# enthaelt_pii
# ---------------------------------------------------------------------------


class TestEnthaeltPii:
    def test_normalfall_erkennt_email(self):
        assert pii.enthaelt_pii("Kontakt: kontakt@alpenbank.at") is True

    def test_normalfall_erkennt_iban(self):
        assert pii.enthaelt_pii("Meine IBAN ist AT611904300234573201") is True

    def test_normalfall_erkennt_telefonnummer(self):
        assert pii.enthaelt_pii("Ruf mich an: +43 664 1234567") is True

    def test_randfall_kein_pii_gibt_false(self):
        assert pii.enthaelt_pii("Welche Hotelkategorie darf ich buchen?") is False

    def test_randfall_leerer_text_gibt_false(self):
        assert pii.enthaelt_pii("") is False

    def test_randfall_kurze_zahl_ist_kein_telefon(self):
        # Eine Kostenstellennummer wie "4711" ist zu kurz, um als
        # Telefonnummer fehlinterpretiert zu werden.
        assert pii.enthaelt_pii("Kostenstelle 4711") is False


# ---------------------------------------------------------------------------
# redigiere
# ---------------------------------------------------------------------------


class TestRedigiere:
    def test_normalfall_email_wird_ersetzt(self):
        ergebnis = pii.redigiere("Kontakt: kontakt@alpenbank.at bitte.")

        assert "kontakt@alpenbank.at" not in ergebnis
        assert "[REDIGIERT: E-Mail]" in ergebnis

    def test_normalfall_iban_wird_ersetzt(self):
        ergebnis = pii.redigiere("IBAN: AT611904300234573201")

        assert "AT611904300234573201" not in ergebnis
        assert "[REDIGIERT: IBAN]" in ergebnis

    def test_normalfall_mehrere_pii_typen_in_einem_text(self):
        text = "Meine E-Mail ist a@b.at, IBAN AT611904300234573201."
        ergebnis = pii.redigiere(text)

        assert "a@b.at" not in ergebnis
        assert "AT611904300234573201" not in ergebnis
        assert ergebnis.count("[REDIGIERT:") == 2

    def test_randfall_text_ohne_pii_bleibt_unveraendert(self):
        text = "Welche Hotelkategorie darf ich buchen?"

        assert pii.redigiere(text) == text

    def test_randfall_leerer_text_bleibt_leer(self):
        assert pii.redigiere("") == ""

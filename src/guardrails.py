"""Eingabe-Guardrails und Session-Budget für den Alpenbank-Assistenten
(Stage 4.4).

Zwei unabhängige Schutzmechanismen für den Live-Modus (im Demo-Modus
nicht relevant – dort entsteht ohnehin kein Token-Verbrauch):

* ``pruefe_nutzereingabe``: validiert die Nutzerfrage, BEVOR sie an den
  Agenten geht (Länge, Steuerzeichen) – schützt vor unnötigem
  Token-Verbrauch und exotischen Eingaben.
* ``budget_ueberschritten``: prüft das kumulierte Session-Token-Budget
  (``settings.SETTINGS.session_token_budget``) – eine grobe Kostenbremse
  gegen eine einzelne, ausufernde Session.

Bewusst frei von Streamlit-Code, damit einzeln testbar. ``app.py``
übersetzt das Ergebnis in UI-Zustand (``st.session_state``, ``st.error``).
"""

from __future__ import annotations

import re

# Maximale Länge einer Nutzerfrage in Zeichen. Schützt vor absurd langen
# Eingaben (z. B. versehentlich eingefügte ganze Dokumente), die unnötig
# Tokens verbrennen würden, ohne die Antwortqualität zu verbessern.
MAX_FRAGE_LAENGE = 2000

# Steuerzeichen außerhalb von Tab (\x09), Zeilenumbruch (\x0a) und
# Carriage-Return (\x0d) sind in einer normalen Chat-Frage nie legitim –
# könnten aber genutzt werden, um nachgelagerte Verarbeitung (Logs,
# Terminal-Ausgaben) zu manipulieren.
_STEUERZEICHEN_MUSTER = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class EingabeAbgelehnt(ValueError):
    """Eine Nutzereingabe wurde von der Input-Sanitisierung abgelehnt.

    Eigene Exception-Klasse (statt generischem ``ValueError``), damit
    ``app.py`` sie gezielt von anderen ``ValueError``-Quellen (z. B.
    ``rag``/``sql``) unterscheiden und mit einer passenden Meldung
    abfangen kann.
    """


def pruefe_nutzereingabe(frage: str) -> None:
    """Validiert eine Nutzerfrage, bevor sie an den Agenten geht.

    Wirft ``EingabeAbgelehnt`` mit einer nutzerverständlichen Meldung bei
    Verstoß. Gibt ``None`` zurück bei einer validen Frage – "kein
    Fehler" ist der Normalfall, den wir nicht extra signalisieren
    müssen.
    """
    if len(frage) > MAX_FRAGE_LAENGE:
        raise EingabeAbgelehnt(
            f"Die Frage ist zu lang ({len(frage)} Zeichen, Maximum "
            f"{MAX_FRAGE_LAENGE}). Bitte kürzer fassen."
        )
    if _STEUERZEICHEN_MUSTER.search(frage):
        raise EingabeAbgelehnt(
            "Die Frage enthält ungültige Steuerzeichen. Bitte reinen "
            "Text eingeben."
        )


def budget_ueberschritten(verbrauchte_tokens: int, budget: int) -> bool:
    """True, wenn das Session-Token-Budget bereits ausgeschöpft ist."""
    return verbrauchte_tokens >= budget

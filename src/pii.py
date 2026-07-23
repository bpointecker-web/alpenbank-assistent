"""PII-Erkennung und -Redaction für den Alpenbank-Assistenten (Stage 4.5).

Regex-basiert statt Presidio (Microsofts NER-basierte Standard-
Bibliothek für PII-Erkennung): keine neue Abhängigkeit, kein
spaCy-Sprachmodell-Download (mehrere hundert MB – dasselbe
Windows-Downloadrisiko wie bei pyarrow, siehe README). Erkennt gängige
strukturierte Muster (E-Mail, IBAN, Telefonnummer) per Substring-Suche.
Nicht so robust wie NER-basierte Erkennung (findet z. B. keine Namen im
Fließtext), reicht aber, um das Konzept im Showroom zu demonstrieren.

Die Demo-Daten sind vollständig synthetisch – es gibt keine echten PII
zu schützen. Angewendet wird die Redaction auf das Audit-Log
(``audit.py``): die Nutzerfrage ist Freitext und könnte – anders als
der kontrollierte Dokumenten-Corpus – reale personenbezogene Daten
enthalten, wenn ein Nutzer sie versehentlich eintippt. Die an Claude
gesendete Originalfrage bleibt unverändert; nur die im Audit-Log
persistierte Kopie wird redigiert.
"""

from __future__ import annotations

import re

_EMAIL_MUSTER = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

# IBAN: zwei Buchstaben (Länder-Code) + zwei Prüfziffern + bis zu 30
# alphanumerische Zeichen (BBAN), optional in 4er-Gruppen mit Leerzeichen
# (übliche Schreibweise). Deckt AT/DE/CH u. a. ab. Keine Prüfsummen-
# Validierung (mod-97) - reine Struktur-Erkennung reicht für Redaction.
_IBAN_MUSTER = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}\b")

# Telefonnummern: optionales führendes +, dann mindestens acht Ziffern/
# Leerzeichen/Bindestriche/Schrägstriche/Klammern. Bewusst großzügig
# (deckt viele Schreibweisen ab), auf Kosten gelegentlicher False
# Positives bei langen Zahlenfolgen ohne Telefonkontext - im Zweifel
# lieber einmal zu viel redigiert als einmal zu wenig.
_TELEFON_MUSTER = re.compile(r"\+?\d[\d\s\-/()]{6,}\d")


def enthaelt_pii(text: str) -> bool:
    """True, wenn der Text mindestens ein erkanntes PII-Muster enthält."""
    return bool(
        _EMAIL_MUSTER.search(text)
        or _IBAN_MUSTER.search(text)
        or _TELEFON_MUSTER.search(text)
    )


def redigiere(text: str) -> str:
    """Ersetzt erkannte PII-Muster durch beschreibende Platzhalter.

    Reihenfolge bewusst E-Mail/IBAN vor Telefonnummer: das großzügige
    Telefonnummern-Muster würde sonst Teile einer bereits ersetzten
    IBAN-Ziffernfolge kein zweites Mal treffen können (schon durch den
    Platzhaltertext ersetzt), aber in der ursprünglichen Reihenfolge
    (Telefon zuerst) könnte es eine IBAN vor deren eigener Erkennung
    zerschneiden.
    """
    text = _EMAIL_MUSTER.sub("[REDIGIERT: E-Mail]", text)
    text = _IBAN_MUSTER.sub("[REDIGIERT: IBAN]", text)
    text = _TELEFON_MUSTER.sub("[REDIGIERT: Telefonnummer]", text)
    return text

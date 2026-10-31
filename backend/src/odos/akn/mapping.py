"""German legal structure -> Akoma Ntoso 3.0 mapping (see Documentation/akn-mapping.md).

AKN element names are labels "either explicitly or due to the local tradition"
(OASIS XSD documentation); they do not carry the German meaning of the same
word. In particular a German "§" is NOT an AKN <paragraph>.
"""

from __future__ import annotations

from odos.document_model import ElementType as T

AKN_NS = "http://docs.oasis-open.org/legaldocml/ns/akn/3.0"
ODOS_NS = "https://github.com/amosproj/amos2026ws04-odos/ns/akn-extension/1.0"

# model type -> (AKN element, eId prefix)
HIERARCHY: dict[T, tuple[str, str]] = {
    T.TEIL: ("part", "part"),
    T.KAPITEL: ("chapter", "chp"),
    T.ABSCHNITT: ("section", "sec"),
    T.UNTERABSCHNITT: ("subsection", "subsec"),
    T.ANLAGE: ("hcontainer", "anlage"),  # generic container, name="anlage" (see docs)
    T.PARAGRAPH: ("article", "art"),  # German § (Paragraph)
    T.ABSATZ: ("paragraph", "para"),  # German Absatz
    T.NUMMER: ("point", "point"),
    T.BUCHSTABE: ("point", "point"),
    T.DOPPELBUCHSTABE: ("point", "point"),
}
CONTAINERS = (T.TEIL, T.KAPITEL, T.ABSCHNITT, T.UNTERABSCHNITT)
ITEMS = (T.NUMMER, T.BUCHSTABE, T.DOPPELBUCHSTABE)
SUBUNITS = (T.ABSATZ, *ITEMS)  # numbered units below an article / paragraph / point

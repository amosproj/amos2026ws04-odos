"""Tiny PDF writer for synthetic test documents (Helvetica, WinAnsi, one text line per entry)."""


def _esc(s: str) -> bytes:
    return s.encode("cp1252", errors="replace").replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def make_pdf(pages: list[list[str]]) -> bytes:
    objs: list[bytes] = []
    n = len(pages)
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n))
    objs.append(b"<</Type/Catalog/Pages 2 0 R>>")
    objs.append(f"<</Type/Pages/Kids[{kids}]/Count {n}>>".encode())
    font_id = 3 + 2 * n
    for i, lines in enumerate(pages):
        page_id, cont_id = 3 + 2 * i, 4 + 2 * i
        objs.append(f"<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents {cont_id} 0 R/Resources<</Font<</F1 {font_id} 0 R>>>>>>".encode())
        ops = [b"BT /F1 10 Tf 12 TL 50 800 Td"]
        for ln in lines:
            ops.append(b"(" + _esc(ln) + b") Tj T*")
        ops.append(b"ET")
        body = b"\n".join(ops)
        objs.append(b"<</Length " + str(len(body)).encode() + b">>\nstream\n" + body + b"\nendstream")
    objs.append(b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica/Encoding/WinAnsiEncoding>>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer<</Size {len(objs) + 1}/Root 1 0 R>>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def paginate(lines: list[str], per_page: int = 55) -> list[list[str]]:
    return [lines[i : i + per_page] for i in range(0, len(lines), per_page)] or [[]]


FILLER = ["Dieser Absatz enthält gewöhnlichen Text ohne besondere Struktur, damit die Seite genügend Zeichen hat."] * 6


def iso_standard() -> bytes:
    lines = ["ISO/IEC 27001:2022", "Information security, cybersecurity and privacy protection", "ICS 35.030", "Reference number ISO/IEC 27001:2022(E)",
             "© ISO/IEC 2022", "Foreword", "ISO (the International Organization for Standardization) is a worldwide federation of national standards bodies."] \
        + ["This document specifies requirements for an information security management system."] * 6
    lines += ["1 Scope", "This document specifies the requirements.", "2 Normative references", "There are no normative references.",
              "3 Terms and definitions", "3.1 Term", "3.1.1 Subterm"] + [f"4.{i} Context of the organization and its requirements" for i in range(1, 20)]
    return make_pdf(paginate(lines + FILLER * 3))


def eu_directive() -> bytes:
    lines = ["Amtsblatt der Europäischen Union", "L 96/357", "RICHTLINIE 2014/35/EU DES EUROPÄISCHEN PARLAMENTS UND DES RATES",
             "vom 26. Februar 2014", "zur Harmonisierung der Rechtsvorschriften der Mitgliedstaaten",
             "DAS EUROPÄISCHE PARLAMENT UND DER RAT DER EUROPÄISCHEN UNION -", "gestützt auf den Vertrag über die Arbeitsweise der Europäischen Union,",
             "in Erwägung nachstehender Gründe:"]
    lines += [f"({i}) Erwägung Nummer {i} mit ausreichend Text, um eine Begründung nachzubilden." for i in range(1, 9)]
    lines += ["HABEN FOLGENDE RICHTLINIE ERLASSEN:", "KAPITEL 1", "Artikel 1", "Gegenstand"]
    for i in range(2, 9):
        lines += [f"Artikel {i}", f"Titel {i}", "(1) Die Mitgliedstaaten treffen alle erforderlichen Maßnahmen."]
    lines += ["Diese Richtlinie ist an die Mitgliedstaaten gerichtet.", "Geschehen zu Brüssel am 26. Februar 2014."]
    return make_pdf(paginate(lines))


def eu_regulation() -> bytes:
    d = eu_directive().decode("latin-1")  # reuse the layout with regulation wording
    lines = ["Amtsblatt der Europäischen Union", "L 96/357", "VERORDNUNG (EU) 2020/1234 DES EUROPÄISCHEN PARLAMENTS UND DES RATES",
             "vom 1. Januar 2020", "über etwas", "in Erwägung nachstehender Gründe:"]
    lines += [f"({i}) Erwägung Nummer {i} mit ausreichend Text, um eine Begründung nachzubilden." for i in range(1, 9)]
    lines += ["HABEN FOLGENDE VERORDNUNG ERLASSEN:", "KAPITEL I", "ALLGEMEINES"]
    for i in range(1, 9):
        lines += [f"Artikel {i}", f"Titel {i}", "(1) Text des Artikels."]
    lines += ["Diese Verordnung ist in allen ihren Teilen verbindlich und gilt unmittelbar in jedem Mitgliedstaat."]
    return make_pdf(paginate(lines))


def shopping_list() -> bytes:
    return make_pdf([["Einkaufsliste", "Brot", "Milch", "Eier", "Käse"]])


def german_law(title: str = "Gesetz über die Förderung der Beispielwirtschaft", n_par: int = 12, with_markers: bool = True) -> bytes:
    lines = [title, "(Beispielwirtschaftsförderungsgesetz - BwFG)"]
    if with_markers:
        lines += ["Ausfertigungsdatum: 01.01.2020", "Vollzitat:", "Beispielgesetz vom 1. Januar 2020 (BGBl. I S. 1)"]
    for i in range(1, n_par + 1):
        lines += [f"§ {i} Überschrift {i}", "(1) Dies ist ein Absatz mit Text, der gewöhnlichen Gesetzestext nachbildet."]
    return make_pdf(paginate(lines))

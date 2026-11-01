"""Command line interface `odos`: process (the whole pipeline), extract, normalize, akn, legal-json (see `odos --help`)."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from odos.extraction import extract_pdf
from odos.parsing import parse_document
from odos.parsing.profiles import for_model, structured_modes


def iso_date(value: str) -> str:
    """argparse type: a calendar date as YYYY-MM-DD (the retrieval date is always stated, never assumed)."""
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a date in the form YYYY-MM-DD: {value!r}") from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="odos")
    sub = parser.add_subparsers(dest="command", required=True)
    extract = sub.add_parser("extract", help="Extract a PDF with Docling")
    extract.add_argument("pdf", type=Path)
    extract.add_argument("-o", "--output-dir", type=Path, default=Path("output"))
    extract.add_argument("--ocr", action="store_true", help="enable OCR")
    norm = sub.add_parser("normalize", help="Build document_model.json from an existing docling_raw.json")
    norm.add_argument("docling_json", type=Path)
    norm.add_argument("-o", "--output-dir", type=Path, default=None, help="default: directory of the input")
    norm.add_argument("--mode", choices=list(structured_modes()), default="german_law", help="parser profile (explicit)")
    norm.add_argument("--pdf", type=Path, default=None, help="the source PDF: writes pdf_text_lines.json (text-layer evidence used to verify/repair the reading order where layout boxes overlap)")  # fmt: skip
    akn = sub.add_parser("akn", help="Generate an Akoma Ntoso excerpt from document_model.json and validate it")
    akn.add_argument("document_model", type=Path)
    akn.add_argument("-o", "--output-dir", type=Path, default=None)
    akn.add_argument("--paragraphs", nargs="+", default=["1", "2"], help="§ numbers to include")
    akn.add_argument("--allow-undated", action="store_true", help="if the source has no Ausfertigungsdatum, label the processing date as such instead of refusing")  # fmt: skip
    akn.add_argument("--retrieval-date", type=iso_date, required=True, help="YYYY-MM-DD: the date the PDF was retrieved (recorded in the XML)")  # fmt: skip
    lj = sub.add_parser("legal-json", help="Serialize a document_model.json to document.json (public JSON) and validate it")
    lj.add_argument("document_model", type=Path)
    lj.add_argument("--docling-json", type=Path, default=None, help="for page sizes; default: docling_raw.json next to the model")
    lj.add_argument("-o", "--output-dir", type=Path, default=None, help="default: directory of the model")
    proc = sub.add_parser("process", help="Run the whole pipeline (extraction, parsing, Legal JSON, Akoma Ntoso) on a PDF")
    proc.add_argument("pdf", type=Path)
    proc.add_argument("-o", "--output-dir", type=Path, required=True)
    proc.add_argument("--mode", choices=list(structured_modes()), required=True, help="parser profile (explicit, never guessed)")
    proc.add_argument("--retrieval-date", type=iso_date, required=True, help="YYYY-MM-DD: the date the PDF was retrieved (recorded in the XML)")  # fmt: skip
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "process":
        return run_process(args)
    if args.command == "akn":
        return run_akn(args)
    if args.command == "legal-json":
        return run_legal_json(args)
    if args.command == "normalize":
        if not args.docling_json.is_file():
            print(f"error: file not found: {args.docling_json}", file=sys.stderr)
            return 1
        if args.pdf is not None:
            from odos.normalization.reading_order import write_evidence

            print(f"evidence:   {write_evidence(args.pdf, args.docling_json)}")
        model = parse_document(args.docling_json, args.mode)
        out = args.output_dir or args.docling_json.parent
        paths = for_model(model).write_reports(model, args.docling_json, out)
        print(f"elements:   {len(model.elements)}")
        print(f"warnings:   {len(model.warnings)}")
        for p in paths:
            print(f"wrote:      {p}")
        return 0
    try:
        res = extract_pdf(args.pdf, args.output_dir, do_ocr=args.ocr)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"status:     {res.status}")
    print(f"pages:      {res.pages}")
    print(f"text items: {res.text_items}")
    print(f"tables:     {res.tables}")
    print(f"json:       {res.json_path}")
    print(f"markdown:   {res.markdown_path}")
    for w in res.warnings:
        print(f"warning: {w}", file=sys.stderr)
    return 0


def run_akn(args) -> int:
    from odos.akn.german_artifacts import build_artifacts
    from odos.artifact_names import AKN_EXCERPT_XML, AKN_REPORT, AKN_TEXT_REPORT, AKN_TRACEABILITY, AKN_XML
    from odos.document_model import DocumentModel

    path: Path = args.document_model
    if not path.is_file():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 1
    model = DocumentModel.model_validate_json(path.read_text(encoding="utf-8"))
    out = args.output_dir or path.parent
    profile = for_model(model)
    if "akn_excerpt" not in profile.capabilities:  # the profile's whole document; --paragraphs does not apply
        art = profile.build_akn(model, args.retrieval_date, out)
        v, t = art["validation"], art["text"]
        print(f"XSD valid:        {v.valid}  (well-formed: {v.well_formed}, errors: {len(v.errors)})")
        print(f"text identical:   {t['same_order_and_text']} ({t['atoms_in_xml']} text atoms), order preserved: {t.get('document_order_preserved')}")  # fmt: skip
        print(f"wrote:            {out}/{AKN_XML}, {AKN_REPORT}, {AKN_TRACEABILITY}, {AKN_TEXT_REPORT}")  # fmt: skip
        for e in v.errors:
            print(f"  line {e.line}: {e.message}", file=sys.stderr)
        return 0 if v.valid and t["same_order_and_text"] else 2
    art = build_artifacts(model, args.paragraphs, args.retrieval_date, out,
                          undated_policy="processing_date" if args.allow_undated else "refuse")
    v, t = art["validation"], art["text"]
    print(f"XSD valid:        {v.valid}  (well-formed: {v.well_formed}, errors: {len(v.errors)})")
    print(f"schema:           {v.schema_version}")
    print(f"text identical:   {t['same_order_and_text']} ({t['atoms_in_xml']} text atoms)")
    print(f"wrote:            {out}/{AKN_EXCERPT_XML}, {AKN_REPORT}, {AKN_TRACEABILITY}")
    for e in v.errors:
        print(f"  line {e.line}: {e.message}", file=sys.stderr)
    return 0 if v.valid and t["same_order_and_text"] else 2


def run_process(args) -> int:
    from odos.pipeline import Outcome, ProcessingMode, run_pipeline

    if not args.pdf.is_file():
        print(f"error: file not found: {args.pdf}", file=sys.stderr)
        return 1
    res = run_pipeline(args.pdf, args.output_dir, ProcessingMode(args.mode), args.retrieval_date,
                       progress=lambda stage: print(f"stage:      {stage}"))  # fmt: skip
    print(f"outcome:    {res.outcome.value}")
    if res.message:
        print(f"message:    {res.message}")
    print(f"output:     {args.output_dir}")
    return 0 if res.outcome == Outcome.COMPLETED else 2


def run_legal_json(args) -> int:
    from odos.artifact_names import DOCLING_RAW, LEGAL_JSON, LEGAL_JSON_REPORT
    from odos.legal_json.artifacts import build_legal_json_artifacts
    from odos.document_model import DocumentModel

    if not args.document_model.is_file():
        print(f"error: file not found: {args.document_model}", file=sys.stderr)
        return 1
    model = DocumentModel.model_validate_json(args.document_model.read_text(encoding="utf-8"))
    out = args.output_dir or args.document_model.parent
    rep = build_legal_json_artifacts(model, args.docling_json or args.document_model.parent / DOCLING_RAW, out)["report"]
    t = rep["text_preservation"]
    print(f"json:       {out / LEGAL_JSON}")
    print(f"report:     {out / LEGAL_JSON_REPORT}")
    print(f"schema:     {'valid' if rep['schema_valid'] else 'INVALID'}")
    print(f"structure:  {'valid' if rep['structure_valid'] else 'INVALID'}")
    print(f"text:       {'identical to the model' if t['identical_to_model'] else 'DIFFERENCES'} ({t['elements_exported']} elements)")
    print(f"footnotes:  {rep['footnotes']['anchored']} of {rep['footnotes']['total']} anchored by source evidence")
    for e in (rep["schema_errors"] + rep["structure_errors"])[:10]:
        print(f"  {e}", file=sys.stderr)
    return 0 if rep["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Command line interface `odos`: extract, normalize, akn, akn4eu, legal-json, classify, serve (see `odos --help`)."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from odos.extraction import extract_pdf
from odos.parsing import parse_document
from odos.parsing.profiles import for_model, structured_modes

# the retrieval date `odos akn` records when none is given (the test inputs' download date)
SOURCE_MD = Path(__file__).resolve().parents[2] / "data" / "input" / "SOURCE.md"


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
    akn.add_argument("--retrieval-date", default=None, help="YYYY-MM-DD; default: from data/input/SOURCE.md")
    a4e = sub.add_parser("akn4eu", help="Export an EU document_model.json in the AKN4EU profile (sample-compatible, AKN 3.1 XSD)")
    a4e.add_argument("document_model", type=Path)
    a4e.add_argument("-o", "--output-dir", type=Path, default=None, help="default: <model dir>/akn4eu")
    a4e.add_argument("--eli", default=None, help="the act's ELI (e.g. http://data.europa.eu/eli/reg/2023/1230/oj); checked against the printed type/number, never derived")  # fmt: skip
    a4e.add_argument("--conversion-date", default=None, help="YYYY-MM-DD for FRBRManifestation; default: today")
    lj = sub.add_parser("legal-json", help="Serialize a document_model.json to document.json (public JSON) and validate it")
    lj.add_argument("document_model", type=Path)
    lj.add_argument("--docling-json", type=Path, default=None, help="for page sizes; default: docling_raw.json next to the model")
    lj.add_argument("-o", "--output-dir", type=Path, default=None, help="default: directory of the model")
    cls = sub.add_parser("classify", help="Classify a PDF (text layer) or a docling_raw.json and show the suggested route")
    cls.add_argument("path", type=Path)
    serve = sub.add_parser("serve", help="Run the local web API (FastAPI)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "classify":
        from odos.classification import classify_lines, lines_from_docling, lines_from_pdf, route

        if not args.path.is_file():
            print(f"error: file not found: {args.path}", file=sys.stderr)
            return 1
        data = lines_from_docling(args.path) if args.path.suffix == ".json" else lines_from_pdf(args.path)
        r = classify_lines(data)
        print(f"type:        {r.document_type.value}\nconfidence:  {r.confidence_band.value} (heuristic band)")
        print(f"route:       {route(r).chosen_mode}  [{r.support_status.value}]\npoints:      {r.points}")
        for e in r.evidence:
            print(f"  +{e.weight} {e.rule_id}: {e.description}" + (f" (p.{e.page}: {e.snippet!r})" if e.snippet else ""))
        for w in r.warnings:
            print(f"warning: {w}", file=sys.stderr)
        return 0
    if args.command == "serve":
        import uvicorn

        uvicorn.run("odos.api.app:app", host=args.host, port=args.port, reload=args.reload)
        return 0
    if args.command == "akn":
        return run_akn(args)
    if args.command == "legal-json":
        return run_legal_json(args)
    if args.command == "akn4eu":
        return run_akn4eu(args)
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


def retrieval_date_from_source() -> str:
    m = re.search(r"Downloaded:\s*(\d{4}-\d{2}-\d{2})", SOURCE_MD.read_text(encoding="utf-8"))
    if not m:
        raise ValueError(f"no 'Downloaded: YYYY-MM-DD' in {SOURCE_MD}")
    return m.group(1)


def run_akn(args) -> int:
    from odos.akn.german_artifacts import build_artifacts
    from odos.artifact_names import AKN_REPORT, AKN_TEXT_REPORT, AKN_TRACEABILITY, AKN_XML
    from odos.document_model import DocumentModel

    path: Path = args.document_model
    if not path.is_file():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 1
    model = DocumentModel.model_validate_json(path.read_text(encoding="utf-8"))
    out = args.output_dir or path.parent
    profile = for_model(model)
    if "akn_excerpt" not in profile.capabilities:  # the profile's whole document; --paragraphs does not apply
        art = profile.build_akn(model, args.retrieval_date or retrieval_date_from_source(), out)
        v, t = art["validation"], art["text"]
        print(f"XSD valid:        {v.valid}  (well-formed: {v.well_formed}, errors: {len(v.errors)})")
        print(f"text identical:   {t['same_order_and_text']} ({t['atoms_in_xml']} text atoms), order preserved: {t.get('document_order_preserved')}")  # fmt: skip
        print(f"wrote:            {out}/{AKN_XML}, {AKN_REPORT}, {AKN_TRACEABILITY}, {AKN_TEXT_REPORT}")  # fmt: skip
        for e in v.errors:
            print(f"  line {e.line}: {e.message}", file=sys.stderr)
        return 0 if v.valid and t["same_order_and_text"] else 2
    art = build_artifacts(model, args.paragraphs, args.retrieval_date or retrieval_date_from_source(), out,
                          undated_policy="processing_date" if args.allow_undated else "refuse")
    v, t = art["validation"], art["text"]
    print(f"XSD valid:        {v.valid}  (well-formed: {v.well_formed}, errors: {len(v.errors)})")
    print(f"schema:           {v.schema_version}")
    print(f"text identical:   {t['same_order_and_text']} ({t['atoms_in_xml']} text atoms)")
    print(f"wrote:            {out}/bdsg_excerpt.xml, {AKN_REPORT}, {AKN_TRACEABILITY}")
    for e in v.errors:
        print(f"  line {e.line}: {e.message}", file=sys.stderr)
    return 0 if v.valid and t["same_order_and_text"] else 2


def run_akn4eu(args) -> int:
    from datetime import date

    from odos.akn.akn4eu_artifacts import build_akn4eu_artifacts
    from odos.document_model import DocumentModel

    if not args.document_model.is_file():
        print(f"error: file not found: {args.document_model}", file=sys.stderr)
        return 1
    model = DocumentModel.model_validate_json(args.document_model.read_text(encoding="utf-8"))
    out = args.output_dir or args.document_model.parent / "akn4eu"
    try:
        art = build_akn4eu_artifacts(model, args.conversion_date or date.today().isoformat(), out, eli=args.eli)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    rep = art["report"]
    c = rep["conformance"]
    print(f"status:            {rep['status']}")
    print(f"files:             {len(rep['files'])} ({rep['act_file']} + {len(rep['files']) - 1} annex file(s)), package {out / rep['package']}")  # fmt: skip
    print(f"AKN 3.1 XSD:       {'valid' if c['oasis_akn_3_1_xsd']['valid'] else 'INVALID'} (official OASIS schema)")
    print(f"AKN4EU samples:    {'all ' + str(c['akn4eu_sample_checks']['rules']) + ' rules hold' if c['akn4eu_sample_checks']['passed'] else 'rules FAILED'} (sample compatibility)")  # fmt: skip
    print("AKN4EU official:   not verified (no official AKN4EU validation artefacts available)")
    print(f"text vs model:     {'identical, order preserved' if c['text_and_order_against_model'] else 'DIFFERENCES'}")
    for f, v in rep["files"].items():
        for e in v["errors"][:3]:
            print(f"  {f}:{e['line']}: {e['message']}", file=sys.stderr)
    return 0 if art["ok"] else 2


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

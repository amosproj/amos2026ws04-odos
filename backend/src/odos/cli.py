"""Command line interface `odos`: process (the whole pipeline), extract, normalize, legal-json, and the optional Amazon
Bedrock steps bedrock-check and extract-rules (see `odos --help`)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from odos.extraction import extract_pdf
from odos.parsing import parse_document
from odos.parsing.profiles import for_model, structured_modes


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
    lj = sub.add_parser("legal-json", help="Serialize a document_model.json to document.json (public JSON) and validate it")
    lj.add_argument("document_model", type=Path)
    lj.add_argument("--docling-json", type=Path, default=None, help="locates the PDF text-layer evidence for the source-fidelity check; default: docling_raw.json next to the model")
    lj.add_argument("-o", "--output-dir", type=Path, default=None, help="default: directory of the model")
    proc = sub.add_parser("process", help="Run the whole pipeline (extraction, parsing, Legal JSON) on a PDF")
    proc.add_argument("pdf", type=Path)
    proc.add_argument("-o", "--output-dir", type=Path, required=True)
    proc.add_argument("--mode", choices=list(structured_modes()), required=True, help="parser profile (explicit, never guessed)")
    sub.add_parser("bedrock-check", help="One minimal request to Amazon Bedrock (checks the API key, region and model; a few tokens)")
    rules = sub.add_parser("extract-rules", help="Extract Rule JSON from a document.json with Amazon Bedrock (paid API calls)")
    rules.add_argument("legal_json", type=Path, help="document.json (Custom Legal JSON 2.0)")
    rules.add_argument("-o", "--output", type=Path, default=None, help="default: rules.json next to the input")
    rules.add_argument("--element-id", action="append", default=None, metavar="ID", help="only this element with its subtree (repeatable); default: the whole document")  # fmt: skip
    rules.add_argument("--dry-run", action="store_true", help="show the scope and the estimated size, do not call Bedrock")
    rules.add_argument("--accept-partial", action="store_true",
                       help="if the answer is still not valid JSON after the allowed retry, use the complete records before the defect (marked partial)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "process":
        return run_process(args)
    if args.command == "bedrock-check":
        return run_bedrock_check()
    if args.command == "extract-rules":
        return run_extract_rules(args)
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


def run_process(args) -> int:
    from odos.pipeline import Outcome, ProcessingMode, run_pipeline

    if not args.pdf.is_file():
        print(f"error: file not found: {args.pdf}", file=sys.stderr)
        return 1
    res = run_pipeline(args.pdf, args.output_dir, ProcessingMode(args.mode), progress=lambda stage: print(f"stage:      {stage}"))
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


def run_bedrock_check() -> int:
    from odos.llm.bedrock import API_KEY_ENV, BedrockClient, BedrockError, load_bedrock_env

    env = load_bedrock_env()  # the Bedrock settings of .env; only names and the file path are ever shown
    print("env file:   " + (f"{env.path} ({len(env.loaded)} Bedrock setting(s) applied)" if env.path else "none found (working directory, its parents, repository root)"))
    try:
        client = BedrockClient()
        cfg = client.config
        print(f"region:     {cfg.region}")
        print(f"model:      {cfg.model_id}")
        res = client.converse("Reply with the single word: ok", "ping", max_tokens=16, temperature=0.0)
    except BedrockError as e:
        print(f"error: {e}", file=sys.stderr)
        if env.path and API_KEY_ENV not in env.present:
            print(f"hint: {env.path} has no non-empty {API_KEY_ENV} line (is the file saved?)", file=sys.stderr)
        return 2
    print(f"answer:     {res.text.strip()[:80]!r}")
    print(f"stop:       {res.stop_reason}")
    print(f"tokens:     {res.input_tokens} in, {res.output_tokens} out ({res.latency_ms} ms)")
    return 0


def run_extract_rules(args) -> int:
    import json

    from odos.artifact_names import RULE_JSON
    from odos.llm.bedrock import BedrockClient, BedrockConfig, BedrockError, load_bedrock_env
    from odos.llm.model_output import default_diagnostics_dir
    from odos.llm.rule_extraction import RuleExtractionError, extract_rules, prepare_request, write_rules_json

    load_bedrock_env()
    if not args.legal_json.is_file():
        print(f"error: file not found: {args.legal_json}", file=sys.stderr)
        return 1
    try:
        legal = json.loads(args.legal_json.read_text(encoding="utf-8"))
        if args.dry_run:
            config = BedrockConfig.from_env()
            req = prepare_request(legal, config, args.element_id)
            print(f"scope:      {req.scope if isinstance(req.scope, str) else ', '.join(req.scope)}")
            print(f"model:      {config.model_id} ({config.region})")
            print(f"input:      about {req.estimated_input_tokens:,} tokens (upper estimate), context window {req.context_tokens:,}")
            print(f"output:     up to {req.max_output_tokens:,} tokens, at most {1 + config.output_retries} model request(s)")
            print("dry run:    nothing was sent")
            return 0
        diagnostics = default_diagnostics_dir()
        result = extract_rules(legal, client=BedrockClient(), element_ids=args.element_id, diagnostics_dir=diagnostics,
                               accept_partial=args.accept_partial)
    except (RuleExtractionError, BedrockError) as e:
        print(f"error: {e}", file=sys.stderr)
        if getattr(e, "diagnostic_ids", None):
            print(f"diagnostics: {diagnostics} (private; contains the model's answer)", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"error: {args.legal_json} is not valid JSON: {e}", file=sys.stderr)
        return 1
    out = write_rules_json(result, args.output or args.legal_json.parent / RULE_JSON)
    g = result.generation
    c = g["counts"]
    print(f"rules:      {c['accepted']} accepted ({c['flagged']} flagged for review, {c['repaired']} repaired), "
          f"{c['rejected']} rejected (of {c['proposed']} proposed)")
    cov = g["coverage"]
    print(f"coverage:   {cov['sentencesCited']}/{cov['sentences']} sentences and {cov['elementsCited']}/{cov['elements']} "
          f"elements cited; {len(cov['citedOnlyByRejected'])} only by a rejected record")
    out_info = g["modelOutput"]
    print(f"tokens:     {g['inputTokens']} in, {g['outputTokens']} out ({out_info['requests']} model request(s))")
    if out_info["partial"]:
        print("warning:    the answer was not valid JSON; only the complete records before the defect were used", file=sys.stderr)
    print(f"rules.json: {out}")
    for r in result.rejected:
        print(f"rejected:   #{r['index']} {r['id']}: {'; '.join(r['reasons'])}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

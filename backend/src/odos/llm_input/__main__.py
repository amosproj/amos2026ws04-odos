"""Run the two parsers on existing Legal JSON, without Docling, a database or an LLM."""
import argparse
import json
from pathlib import Path
from odos.llm_input.artifacts import write_input_artifacts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("legal_json", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    legal = json.loads(args.legal_json.read_text(encoding="utf-8-sig"))
    report = write_input_artifacts(legal, args.output_dir)
    print(json.dumps({"characters": report["characters"], "estimatedTokens": report["estimatedTokens"],
                      "policy": report["applicability"]["policy"]}, indent=2))


if __name__ == "__main__":
    main()

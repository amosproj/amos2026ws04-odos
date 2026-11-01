# Repository handoff

This folder contains the research deliverables for ODOS issue #11. It can be moved as one unit because paths inside the demonstration resolve relative to `demo.py` and documentation links are relative.

## Suggested placement

A suitable destination in the team repository is:

```text
Documentation/research/shacl-pyshacl/
```

This is a suggested location, not an agreed repository convention. Keep the folder structure intact so report links and source references continue to work.

## Files to include

Include the Python sources, `pyproject.toml`, `uv.lock`, `uv.toml`, `.gitignore`, `.gitattributes`, report, README, notices, supplied PDF fixture, `rules/`, `samples/`, the reviewed `output/` evidence and `presentation/`.

Do not commit `.venv/`, `__pycache__/`, OS metadata, personal `my-*` experiments, local slide-build intermediates or transfer ZIP files. The local `.gitignore` covers these exclusions. Do not run `git add -f` to bypass it.

The transfer ZIP prepared alongside this folder contains only the selected handoff files, without any `.git` directory or Python environment. The archive is intended for unpacking into the team repository, not for committing as a second copy of all artifacts.

## Validation after moving

From the moved research folder:

```bash
uv sync --locked
uv run --locked demo.py
uv run --locked collect_evidence.py
```

The fixed sample suite should report `17/17 tests passed`. The evidence collector should verify provenance and the JSON threshold experiment. A fresh run updates timestamps, generated RDF blank-node identifiers and fingerprints, which may create expected diffs in committed evidence.

## Before the actual push

Review the selected files and their diff in the destination repository. Retain source attribution in `THIRD_PARTY_NOTICES.md`; the source PDF is not claimed as original project-authored content. Keep the scope and interpretation assumptions in the report and rule template. Complete the team's normal review, product-owner approval and merge process.

No remote push, commit, issue closure or mainline merge is part of preparing this handoff package. Local demonstration tests do not replace checks required by the destination repository.

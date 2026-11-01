# Partner-provided test inputs (not in Git)

The Musterbauordnung (MBO) and Regulation (EU) 2023/1230 were supplied by the industry partner as files and are
not redistributed. Keep them under `backend/data/input/private/` (gitignored) or point `ODOS_MBO_PDF` /
`ODOS_EU_PDF` at them; the tests that need them skip with a printed reason when they are absent.

| File | SHA-256 |
|---|---|
| `private/MusterBauVerordnung.pdf` | `53fd13388013263c3f676a3a8024f6932e38b8d326af6d2d844ecb9be61d340c` |
| `private/eu_2023_1230.pdf` | `fe36f0d148a84e790ec9a9825017baaea66fb931a5314ad0a614a1cde0ec182c` |

No public law is stored in this repository. The always-running tests use the synthetic German law
(`tests/synthetic_german.py`) and the synthetic EU regulation (`tests/synthetic_eu.py`): original text with generated
PDFs, freely redistributable.

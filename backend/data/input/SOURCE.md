# Test input: BDSG.pdf

- Document: Bundesdatenschutzgesetz (BDSG), 2018 version
- Source URL: https://www.gesetze-im-internet.de/bdsg_2018/BDSG.pdf
- Downloaded: 2026-10-27
- Size: 267512 bytes, 45 pages
- SHA-256: `859631d6203e0c3d12b280a1982c83d0521ccfe6c4eaa04ae5bc264112711004`

Verify with `shasum -a 256 data/input/BDSG.pdf`. The upstream file is updated
when the law is amended, so a re-download may differ; the tests check this hash.

# Partner-provided test inputs (not in Git)

The Musterbauordnung (MBO) and Regulation (EU) 2023/1230 were supplied by the industry partner as files and are
not redistributed. Keep them under `backend/data/input/private/` (gitignored) or point `ODOS_MBO_PDF` /
`ODOS_EU_PDF` at them; the tests that need them skip with a printed reason when they are absent.

| File | SHA-256 |
|---|---|
| `private/MusterBauVerordnung.pdf` | `53fd13388013263c3f676a3a8024f6932e38b8d326af6d2d844ecb9be61d340c` |
| `private/eu_2023_1230.pdf` | `fe36f0d148a84e790ec9a9825017baaea66fb931a5314ad0a614a1cde0ec182c` |

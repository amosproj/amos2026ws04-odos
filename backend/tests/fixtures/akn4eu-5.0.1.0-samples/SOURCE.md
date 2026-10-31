# Official AKN4EU 5.0.1.0 samples (XML only, unmodified)

- Source: AKN4EU sample package `akn4eu-5.0.1.0-samples.zip` (Publications Office of the European Union,
  EU Vocabularies, dataset AKN4EU: https://op.europa.eu/en/web/eu-vocabularies/dataset/-/resource?uri=http://publications.europa.eu/resource/dataset/akn4eu),
  provided by the project team on 2026-10-29
- ZIP SHA-256: `767cd8ceaf863319c6599a305d8186b03342137fdd252d7adca6a305256adb51`
- Copied: the 60 `*.xml` files, byte for byte, in their original folder structure. Not copied: the
  source PDF/DOC/DOCX files, the two `.leg` packages (ZIP files whose XML members are the XML files of the
  same folder), macOS metadata. `SHA256SUMS` lists every copied file.
- The files declare `akn4eu:akn4euVersion value="5.0.0.1"`; the package is labelled 5.0.1.0.

Used by `tests/test_akn4eu.py` as reference examples: all 60 validate against the OASIS AKN 3.1 schema
(`schemas/akn-3.1-os`), 29 of them failed the former AKN 3.0 schema, and every rule of `odos.akn.akn4eu_checks` holds for
all of them. Reuse of Publications Office content: Commission Decision 2011/833/EU.

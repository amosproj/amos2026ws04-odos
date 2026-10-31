# Official OASIS Akoma Ntoso 3.1 schema (unmodified)

- Standard: Akoma Ntoso Version 2.0, Part 2: Specifications of AKN 3.1, OASIS Standard (approval stage `os`, published 2026-10-02)
- Namespace: `http://docs.oasis-open.org/legaldocml/ns/akn/3.0` (unchanged from 3.0; `akomaNtoso/@version` is fixed to `3.1`)
- Source: https://docs.oasis-open.org/legaldocml/akn-core/v2.0/os/part2-specs/schemas/
- Retrieved: 2026-10-29

| File | SHA-256 |
|---|---|
| `akomantoso30.xsd` | `8f1fe3e187ee5e6f5bc9dfb013f7d9195de6516f077ce10726bedf6260f8b70a` |
| `xml.xsd` | `61960fb3131e38022caad5360e2f33a3382578ab3c80cd58bd74320ede61b20c` |

Both digests equal the ones in the OASIS release manifest, which is stored next to them as
`akn-core-v2.0-os-part2-specs-manifest.txt` and `manifest.json` (downloaded from `../` of the source URL).
The file keeps its historical name `akomantoso30.xsd`; it is the AKN 3.1 schema.

Why this schema: AKN4EU 5.x is based on AKN 3.1 (Publications Office, EU Vocabularies, "Schemas" page).
All 60 XML files of the official AKN4EU 5.0.1.0 samples validate against this schema; 29 of them
failed the former AKN 3.0 schema (`annex`, `thead`/`tbody`, `FRBRlanguage/@refersTo`, ...).
It is the only schema ODOS validates against (all export profiles). The AKN 3.0 schema
(`schemas/akn-3.0-os/`, OASIS Standard 2018) was removed on 2026-10-29 after every export and every
stored review revision had been validated against AKN 3.1.

`odos.akn.validate` refuses to run if a hash differs.

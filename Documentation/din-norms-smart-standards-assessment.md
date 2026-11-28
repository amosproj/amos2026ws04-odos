# DIN norms and SMART Standards assessment (Issue #99)

Research result for Sprint 7, as of 28 November 2026. It is a proposal: the team and the Product Owner have not approved it. It is not legal advice. Nothing recommended here is implemented by this issue.

Presentations: [executive summary, 6 slides](../Deliverables/sprint-07/din-norms-smart-standards-assessment/odos-smart-standards-executive-summary.pptx) and [technical assessment, 12 slides](../Deliverables/sprint-07/din-norms-smart-standards-assessment/odos-smart-standards-technical-assessment.pptx).

## Recommendation

| Topic | Decision |
|---|---|
| German and EU legislation | **Go.** Keep the PDF and Docling pipeline. |
| Licensed technical standards (PDF) | **Conditional.** Only after the needed rights are confirmed in writing and the safeguards below are in place. |
| ReqIF backend importer | **Proposed should-have,** limited in scope, subject to compatibility tests, capacity and Product Owner approval. |
| ReqIF upload and viewer | **Stretch goal.** |
| Nexus AI, provider APIs, NISO STS | **Deferred.** Not needed for the minimum product. |
| Protected content without confirmed rights | **Do not process.** |

The first priority is one reliable end-to-end Digital Twin validation workflow.

## 1. Document families and legal regimes

The partner's document list is confidential. This public document therefore describes legal regimes only. It contains no per-entry classification and no counts.

| Family | Access | Processing and AI use | ODOS |
|---|---|---|---|
| German federal and state law | Official portals | No copyright in official legislative texts (§5(1) UrhG); portal terms for state law not checked | Go |
| EU directives and regulations | EUR-Lex | Reuse allowed unless stated otherwise, under the EUR-Lex legal notice; third-party content excluded | Go |
| Model codes, such as the Musterbauordnung | Publisher | A model code is not binding state law; check which state regulation and edition applies | Check per use |
| DIN, DIN EN, DIN EN ISO | Purchase or subscription | Separate permission; DIN offers an AI licence | Conditional |
| VDE-distributed standards | Content licence | Standard purchase terms prohibit AI processing | Rights first |
| Standalone ISO and IEC | Purchase or subscription | Separate permission | Hold |
| Other technical rules and association publications | Varies | Each publisher's own terms; not all reviewed | Hold until confirmed |

A law that refers to a private standard without reproducing its wording does not remove that standard's copyright (§5(3) UrhG).

## 2. Conditions for processing paid standards

Buying a standard, or being able to read it (for example through a university or an information point), does not by itself permit machine processing, AI use or export.

| Provider | Published position |
|---|---|
| DIN Media AI licence | For a company's own PDF stock, or for XML content in a Nautos collection. Requires bought or subscribed content, the matching internal reproduction right (DIN membership or network licence) and an internal, encapsulated AI environment without training public or external models. Excludes VDE. Individual offer. |
| DIN Media Nautos ReqIF converter | Needs XML content in Nautos, the converter module and network reproduction rights. AI rights for exported ReqIF are not addressed. |
| VDE Verlag business terms | §8.3 prohibits processing by an AI system, including upload. §1.1 allows deviations that the publisher confirms in writing. |
| VDE Nexus ReqIF | Paid add-on to a content or subscription licence. Exports `.reqif` and `.reqifz` following DIN DKE SPEC 99200. Price on request. It does not by itself establish permission to send content to an external AI service. |
| VDE Nexus AI | Separate retrieval service over MCP or REST, currently IEC standards in English. Usable without Nexus ReqIF. It does not guarantee complete extraction of a document. Price on request. |
| ISO | Licence agreement §6b and §7b require additional licences for digital transformation and for AI or machine learning use. |
| IEC | Webstore terms §3 require express permission for use in software or AI tools. |

Gates before any protected standard is processed:

1. **Contract.** Written confirmation covering the content, parsing, AI processing in our own Amazon Bedrock setup, storage, export of derived Rule JSON, sharing of results and access by the student team.
2. **Cloud.** AWS documents that content is not used to train base models or shared with model providers. The configured EU inference profile can route requests between several EU regions. Retention, invocation logging and access control in the AWS account were not inspected. No rights holder has approved this setup.
3. **Security.** `compose.yaml` writes extraction results and reports, which contain source text, into `dev-fixtures/bedrock-extraction-results` and `dev-fixtures/Reports_for_results` inside this public repository. Disable or move this output first. The review API also has no authentication.

Docling runs machine learning models for layout and tables. Our cautious reading is that local parsing of a protected PDF therefore also needs permission where terms restrict machine or AI processing. A self-hosted model does not remove licence requirements.

## 3. IDiS, SMART Standards and ReqIF

IDiS is the digital standards initiative of DIN and DKE. SMART Standards are its goal: standards content that machines can read and apply. ReqIF is one XML exchange format, profiled for standards by DIN DKE SPEC 99200:2025-03 (free, based on ReqIF 1.2).

| IDiS work | Published state | Use for ODOS |
|---|---|---|
| Digital requirements with ReqIF (since August 2023) | SPEC 99200 and examples; a PDF-to-ReqIF pilot without a published converter | The specification guides an importer |
| Conformity testing (2021–2022) | Prototype matching machine-readable limits in a test setup | Concept only |
| NormAAS (2021–2024) | Demonstrator matching requirements with product capabilities through the Asset Administration Shell | Concept only |
| AI-based requirements engineering (November 2025 to October 2026) | Listed as running; no results found | None yet |
| Scalable AI testing (2024–2025) | Whitepaper; describes delivery of standards by API as feasible | Orientation |

SMART Standards help ODOS with stable identifiers, hierarchy, attributes and traceability. No ready-made component that ODOS could plug in was identified. ReqIF avoids layout reconstruction, but the requirement text still needs interpretation: it is not executable rule logic, and human review remains necessary.

## 4. Technical evidence

Both experiments ran outside this repository on 27 November 2026, against `develop` at `01d8b5c`.

- **ReqIF.** StrictDoc `reqif` 0.1.1 (Apache-2.0) on Python 3.12 parsed a self-written file as `.reqif` and `.reqifz` (four objects, one relation, no XSD errors). A throwaway adapter produced Legal JSON that passed the existing schema and structure checks with placeholder metadata. The rule response was written by hand; no model was called.
- **Gaps found.** The parser accepts DTDs and duplicate or dangling identifiers, has no size limit for archives and can raise raw errors. The current model drops ReqIF attributes and relations. Upload, database and viewer assume PDF.
- **Technical-standard PDF parser.** The unmerged branch `feature/technical-standard-parser` (`b44074c`) merged into a scratch copy without conflicts: 862 backend tests passed (169 of them the parser's own), 66 were skipped and 15 slow tests were not run. No real standard was tested. A matching prompt and clause-level chunking are missing.

Not measured: extraction quality on real standards, and any saving in time or tokens.

## 5. Architecture and effort

All inputs converge into one core: Document Model, Legal JSON 2.0, LLM Input Builder, Amazon Bedrock, Rule JSON 2.0 and human review, followed by semantic mapping, fact normalisation and Digital Twin validation. A rights check comes before protected content. A ReqIF adapter would be a second input; it needs additive source metadata, not a second rule model or database. Validation results are PASS, FAIL, UNKNOWN or NOT APPLICABLE, and missing or ambiguous information must never become a PASS. The validation technology is still under evaluation.

| Work | Estimate (story points) |
|---|---|
| Next document on the existing path | 1–3 |
| Licensed PDF route | 5–8 |
| ReqIF compatibility and safety tests, then backend importer | 3 + 5 |
| ReqIF web integration | +5–8 |
| Rights safeguards | 3–5 |
| Semantic mapping and validation, shared with Issue #97 and counted once | 8, preliminary |

These are analyst estimates, not team commitments. Content and AI licences are priced by quote. The `reqif` library has no licence fee; Bedrock is billed by usage.

Proposed order: Sprint 7 research; Sprint 8 next document, licence questions, ReqIF tests and start of mapping; Sprints 9–10 ReqIF backend, mapping and validation (reduced holiday capacity in Sprint 10); Sprint 11 integration and feature freeze; Sprint 12 regression and demo preparation; Demo Day on 3 February 2027. If capacity drops, defer ReqIF web integration first, then the ReqIF backend.

## 6. Next document

**Low Voltage Directive 2014/35/EU, German version** (consolidated version of 30 May 2026).

- Official text that can be reused under the EUR-Lex terms, so no licence is needed to start.
- Relevant to the electrical domain (equipment rated 50–1000 V AC or 75–1500 V DC, with exclusions).
- Fits the existing EU legislation path and tests how ODOS handles a directive.

The German implementing ordinance, 1. ProdSV, is a useful complement. Neither document has been run through the pipeline yet, and the safety objectives in Annex I are largely qualitative, so it is a document pilot and not necessarily an easy validation case. DIN EN ISO 13857 is a possible later pilot, only with confirmed rights.

## 7. Open questions

- Which licences does the partner already hold, and what would DIN Media or VDE offer?
- Do the rights holders accept processing in Amazon Bedrock, including storage and export of derived rules?
- Does the DIN AI licence cover ISO content in DIN EN ISO editions and ReqIF exports?
- Which Digital Twin data may be used and shared?

## 8. Coverage and Definition of Done

| Acceptance criterion | Coverage |
|---|---|
| Separate EU law from paid standards without forcing other categories into either group | Covered by legal regime (section 1); per-entry classification not published |
| Whether and under what conditions paid standards' text can be processed | Covered from published terms (section 2); contracts unconfirmed |
| What IDiS SMART Standards offer and whether they help ODOS | Section 3 |
| Select and justify the next document | Section 6 |

Saving the findings in `Documentation/` is done with this file. Review, merge, tests and Product Owner approval are still required.

## Sources

Checked on 27 November 2026; the VDE terms and Nexus AI page again on 28 November. The ISO terms could not be re-opened by the later automated check.

- Law: [§5 UrhG](https://www.gesetze-im-internet.de/urhg/__5.html), [EUR-Lex legal notice](https://eur-lex.europa.eu/content/legal-notice/legal-notice.html?locale=en), [Directive 2014/35/EU](https://eur-lex.europa.eu/eli/dir/2014/35/oj/eng), [1. ProdSV](https://www.gesetze-im-internet.de/prodsg2011v_1/)
- DIN: [AI licence](https://www.dinmedia.de/de/normen-produkte/ki-lizenzen-fuer-normen), [Nautos ReqIF converter](https://www.dinmedia.de/de/normen-management/nautos/software/modul-reqif-konverter), [DIN DKE SPEC 99200](https://www.dinmedia.de/de/technische-regel/din-dke-spec-99200/389211467)
- VDE: [terms](https://www.vde-verlag.de/agb), [Nexus ReqIF](https://www.vde-sis.de/de/vde-nexus/reqif/), [Nexus AI](https://www.vde-sis.de/de/vde-nexus/nexus-ai/)
- ISO and IEC: [ISO licence agreement](https://www.iso.org/terms-conditions-licence-agreement.html), [IEC Webstore terms](https://webstore.iec.ch/en/terms-conditions)
- IDiS: [overview](https://www.dke.de/idis), [pilot projects](https://www.dke.de/idis/pilotprojekte)
- Technology: [StrictDoc reqif](https://github.com/strictdoc-project/reqif), [Bedrock data protection](https://docs.aws.amazon.com/bedrock/latest/userguide/data-protection.html), [Bedrock cross-region inference](https://docs.aws.amazon.com/bedrock/latest/userguide/geographic-cross-region-inference.html)

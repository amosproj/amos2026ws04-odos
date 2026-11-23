> Frontend update: the random-sample controls described below have been replaced by an article/§ checklist and Whole document. See article-checklist-extraction.md. Legacy sample API fields remain supported.

# Random four-article samples

This cumulative update includes the previous stop, additive restart, preview/call limits, and artifact/navigation frontend changes. Merge frontend, backend and Documentation into your current newer develop project; replace matching files and keep .env. Do not delete existing project folders or Docker volumes.

```powershell
docker compose up --build -d
```

In LLM Rule Extraction, open Preview Rule Extraction:

- **1 sample:** randomly picks up to four distinct eligible articles and sends them together as ONE extraction chunk. With the default one-call budget, this means one initial LLM call, not four calls.
- **3 samples:** randomly picks up to twelve distinct eligible articles, divided into at most three chunks of four. No provision repeats within the selection.
- **All remaining:** retains the existing full-document chunking strategy.

For MBO, § provisions are used instead of articles. If fewer eligible provisions remain, only those are selected; nothing is duplicated to fill a group. Annexes/chapter containers are not used as article substitutes. V2 exclusions and protected accepted/edited provisions are respected. Mixed protected/pending provisions follow the existing additive restart policy, preserving previous rules.

The preview shows article numbers and titles. Changing the call budget keeps the same seed/selection. Choose another random sample produces a new preview without calling the LLM. Starting passes the displayed article IDs to the backend; if they are no longer eligible, the server refuses and asks for a fresh preview. It never silently swaps them for different articles. The actual sample list is saved in the extraction report. Direct-reference context can include supporting text outside the selected target articles.

Samples can still be long, and four articles may exceed a configured context limit. The preview reports size/readiness before any paid extraction. Generated output remains subject to its existing limit and human review. This is not a full-document or representative compliance check.

Validation: 32 offline backend tests passed with fake AWS/repository boundaries. Checks include four real articles in one model payload, three disjoint groups, stable preview/start selections, changed eligibility, MBO fallback, V2 filtering and the existing stop/review preservation checks. Local preparation against the supplied EU and MBO Legal JSON files produced one four-provision request for each, without paid inference. Changed TS/TSX parsed/transpiled. Full Docker/TypeScript/Vitest and live AWS/PostgreSQL integration were not run here.

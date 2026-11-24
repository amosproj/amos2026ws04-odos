# Article checklist and whole-document extraction

This cumulative update replaces random selection in the frontend with two choices:

- **Choose articles / § provisions:** a searchable checklist with number and title, Select all eligible, and Clear selection. Nothing is selected by default. Check one or more provisions; preview and Start use exactly those IDs. Selected provisions are grouped in document order into requests of at most four. Choose at most 100 manually, or use Whole document for a larger scope.
- **Whole document:** uses the existing normal V2 full-document chunking, including non-article material such as annexes. Previous accepted rules and manual edits remain protected and preserved under the additive restart policy.

V2 exclusions are not offered as selectable articles. Accepted/edited provisions that are fully protected are listed but disabled. Mixed protected/pending provisions may still be processed while their protected rules are retained. Manually edited rules are never automatically approved. New candidates still require review. The 1/3-call selector and cooperative Stop behavior are unchanged.

Opening the checklist and preparing estimates make no model requests. The start button remains disabled for an empty selection, while estimates are loading, or when no selected chunk fits. Changing the checklist or call limit invalidates the old estimate. Supporting direct-reference context may include text outside the selected extraction targets; only checked provisions are targets. Checklist runs are explicitly partial. A changed/stale protected selection is rejected rather than silently replaced.

## Apply

The ZIP contains new/updated files, not a standalone project. Merge backend, frontend and Documentation into your existing newer develop project root beside compose.yaml; replace matching files and retain .env and the other project files. Previous stop, review-preservation, V2 integration, artifact and navigation updates are included.

```powershell
docker compose up --build -d
```

Open LLM Rule Extraction, then Preview Rule Extraction. Choose articles / § provisions or Whole document, review the estimate, and click Start paid extraction.

## API

Both preview and start endpoints accept articleIds:

- `{ "maxModelCalls": 1, "articleIds": [] }`: checklist discovery and zero-token preview. Starting with an empty selection is rejected.
- `{ "maxModelCalls": 1, "articleIds": ["actual-article-id"] }`: explicit selection.
- `{ "maxModelCalls": 1, "articleIds": null }`: whole document.

IDs must come from availableArticles in the preview, whose entries include eligibility, number and title. The preview echoes articleIds, and selectedArticleIds gives document-order targets. Existing elementIds can still narrow the document. Random sample fields remain supported only for backwards compatibility and cannot be combined with articleIds. Selection details are stored in the generation metadata and report.

## Verification

41 offline backend checks passed with AWS/repository boundaries replaced by fakes. They include empty discovery, exact checked targets in a model payload, grouping selections larger than twelve articles, whole-document annex handling, V2 filtering, protected/stale/duplicate selections, MBO § labels, source immutability, and selected-worker output metadata, plus existing stop/review-preservation tests. Frontend TS/TSX parsed/transpiled; lightweight component checks covered empty and protected-item disabling, exact selected IDs, stale-preview blocking, and Whole document. Full TypeScript/Vitest/Docker build and live AWS/PostgreSQL tests were not available here. No paid inference was performed.

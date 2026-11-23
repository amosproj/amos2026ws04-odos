# Extraction preview and correction limits

On the LLM Rule Extraction page, choose **Preview Rule Extraction**. The preview prepares the actual V2 chunk prompts locally. It does not create an extraction, change stored results, or call Bedrock. It shows the model, ready/total chunks, estimated initial input tokens, maximum workflow calls, and output token ceilings.

Choose **1 call** (default for testing) or **up to 3 calls** per chunk, then click **Start paid extraction**. One call means one initial response and no correction requests. Three means the initial response plus at most two JSON/schema correction requests. Valid responses can finish after one call in either mode. Validation checks and reports still run in both modes; results remain drafts. The setting is applied independently to every chunk, not to the whole document. Invalid and partial candidates retain their existing reporting behavior.

Restarts and retries also open the preview before a new extraction. Opening a stored result remains free of model calls. V2 remains the extraction input; the custom Legal JSON, V1 and V2 outputs and downloads remain available.

The input estimate includes repeated instructions, schema, and direct-reference context for initial requests. Correction prompts and output length are unknown in advance. The output ceilings are possible maxima, not expected usage or a currency estimate. Counts refer to workflow calls; SDK transport retries remain configured separately. No hard monetary budget or article selector is added.

## API

`POST /api/jobs/{job_id}/rule-extraction/preview`

`POST /api/jobs/{job_id}/rule-extraction`

Both accept `{ "maxModelCalls": 1 }` or `{ "maxModelCalls": 3 }`, optionally with the existing `elementIds`. Omission defaults to 1. Other values are rejected. The preview does not require an AWS credential, but model/context configuration must be valid. Starting extraction still requires Bedrock configuration.

The selected limit is persisted in extraction status and recorded per chunk and in merged reports. This is a per-run option, not a global mutable setting, so concurrently planned runs cannot change each other's policy.

## CLI

`odos extract-rules path/to/document.json --dry-run --max-model-calls 1`

`odos extract-rules path/to/document.json --max-model-calls 3`

The CLI also defaults to 1.

## Apply and run

Copy the files in the ZIP into your repository root, alongside `compose.yaml`, preserving their relative paths and replacing matching files. Keep your existing `.env`.

From your repository root:

```powershell
docker compose up --build -d
```

Open the existing frontend URL, process a document, continue to LLM Rule Extraction, and open the preview. Cancelling a preview does not start extraction. One call per chunk can still mean many calls when processing a whole document.

## Verification

Offline checks exercised prompt estimates, V2 selection, strict limit validation, one/three-call behavior, per-chunk propagation, and preserving existing results on a failed run, using fake responses. TypeScript/TSX syntax was parsed. Full pytest and Vitest/build could not run in the editing environment because the project test/build dependencies were unavailable; regression tests for the normal repository environment are included. No live model call was made.

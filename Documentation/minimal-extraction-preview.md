# Minimal extraction preview

The correction-setting dropdown, Maximum workflow calls, and Output token ceiling per call are hidden from the frontend preview. The frontend always uses maxModelCalls=1 (no correction requests). The API still supports its existing explicit 1/3 call setting for other clients. The run-wide output ceiling stays visible.

The note now reads: "Input is an estimate for initial requests, including repeated prompts and reference context. Correction input and generated output are unknown."

This cumulative update keeps article selection, whole-document mode, rule preservation, Stop, and the digital-twin mock page. Merge the ZIP folders into the existing project root beside compose.yaml, replace matching files, retain .env, and run:

```powershell
docker compose up --build -d
```

Verification: frontend syntax/transpilation, backend Python compilation, absence of the hidden fields, presence of the total output field, and lightweight checklist interaction checks passed. Full Docker/TypeScript/Vitest builds were not run here. No live LLM request was made.

# ODOS DEMO2: LLM verification

DEMO2 starts with the interpreted rules from DEMO and an RDF digital twin. RDFLib projects the relevant facts for one explicitly typed target. The configured model receives those facts and the existing rules, then returns a structured judgment per rule. Python validates the response and attaches the original RDF evidence. The model performs the substantive verification, including numeric comparisons, roof alternatives and setback arithmetic.

The rule snapshot and Turtle examples come from the sibling DEMO. The supported profiles cover the existing demo interpretations of MBO §37(5) and §6(5) sentence 1. The original rule assumptions are in `rules.json`. The app does not run PDF extraction or a SHACL engine.

The job routes follow the main ODOS API pattern. The submission body here is JSON with RDF rather than a multipart PDF upload, so the existing PDF frontend needs an adapter. The separate prototype_pyshacl experiment uses a different RDF vocabulary. Its fixtures need explicit mapping before they can be used here.

## Run

Use an installed Python 3.12+ and uv. Set the API key in the shell that starts FastAPI. For the official DeepSeek API, the base URL defaults to `https://api.deepseek.com` and the model defaults to `deepseek-flash`. A gateway must support Chat Completions with [JSON Output](https://api-docs.deepseek.com/guides/json_mode/).

```bash
uv sync --locked
read -rsp 'DeepSeek API key: ' DEEPSEEK_API_KEY
printf '\n'
export DEEPSEEK_API_KEY
# For a gateway, set DEEPSEEK_BASE_URL and ODOS_LLM_MODEL to its endpoint and model ID.
uv run --locked uvicorn app:app --host 127.0.0.1 --port 8001
```

`DEEPSEEK_BASE_URL` accepts an API base URL (including a gateway's `/v1` prefix) or a full URL ending in `/chat/completions`. Keep the key in the server environment.

Open http://127.0.0.1:8001/docs. The health route reports API readiness. Verification jobs send the selected subject, rules and projected facts to the configured endpoint.

## Try a case

1. Call `GET /api/examples/valid_boundary` and copy its JSON response.
2. Submit it as the body of `POST /api/jobs`. The endpoint returns HTTP 202 and a job ID.
3. Poll `GET /api/jobs/{job_id}`. A completed job exposes `GET /api/jobs/{job_id}/files/verification_report.json`. A failed job includes an error message.
4. Remove a finished job with `DELETE /api/jobs/{job_id}`.

The example routes also serve `too_narrow`, `missing_width`, `roof_step_alternative`, `setback_boundary`, `setback_too_small` and `no_target`. For a custom input, submit Turtle in `rdf` and select `escape_window` or `general_setback`. If there are several targets, supply the exact full IRI in `subject`. Each request verifies one target.

The report includes the rule IDs, model name, cited evidence fields, original RDF values, per-rule verdicts and explanations. Overall status is derived from the model judgments: a failure takes precedence, then uncertainty, then pass. Missing evidence can produce `unknown`. The roof-distance rule can be `not_applicable` for a non-roof window. A missing target returns HTTP 422 before model inference.

This is an exploratory verifier. Model judgments can be wrong even if they conform to the JSON schema and cite real input fields. Compare the judgments with the known fixtures when evaluating a model. The small in-memory queue processes one job at a time and clears when the API restarts.

## Smoke tests

```bash
uv run --locked python -m unittest -v
```

The tests substitute model replies to check the API, evidence mapping, job failures and the no-target guard. Run the example jobs against the configured server to evaluate actual model accuracy.

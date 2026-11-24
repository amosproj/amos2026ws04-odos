# Simplified extraction preview labels

The visible Text groups counter is removed. The call-limit selector is labeled Correction setting and retains exactly these options:

- 1 call - no corrections
- 3 calls - up to 2 corrections

The default remains 1. This is a presentation change; internal selection, grouping, model budgets, stop handling, retained reviews, and the digital twin preview remain as implemented.

Input tokens estimate all initial prompt text across requests, including repeated instructions/schema and supplied reference context. Previous rules kept counts existing rules retained in the additive collection, including unaccepted ones. Protected targets skipped counts document targets omitted from regeneration because their existing rules are all accepted or manually edited. Maximum workflow calls includes initial and allowed correction requests. Output token ceiling per call limits each generated answer; the run ceiling multiplies this by the maximum workflow calls. These are usage ceilings, not predicted output or a price quote; SDK transport retries are separate.

A local preparation check confirmed that ten eligible article IDs produce three internal requests in the current code. The reason a previous run displayed two cannot be determined from the pasted counters alone.

Apply the cumulative update by merging backend, frontend and Documentation into the existing project root, replacing matching files and retaining .env and all other project files. Then run docker compose up --build -d. Frontend syntax and removal of the counter were verified; a full Docker build was not run here.

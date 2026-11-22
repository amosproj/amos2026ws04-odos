# Rule extraction reports

Each new workflow result in `../bedrock-extraction-results/` has a report with the
same timestamped basename: `<name>.rules.json` pairs with `<name>.report.json`.
Both carry the same `runId`. Timestamps in filenames use UTC.

Current document reports contain an ordered `chunks` list. Each entry embeds its
individual report, including the supplied target/context document, raw responses,
schema feedback, check messages and token usage. `integration` records failed,
empty or truncated chunks, ID changes, possible duplicates and unresolved context
or source references. `ruleOrigins` maps merged records to their original chunks.
The top-level checks run again on the merged result without a model call.
Workflow version 4 runs up to four chunks concurrently and waits for all of them
before merging in source order. `maxWorkers`, per-chunk timestamps/durations and
the top-level `timing` object show queue wait, overlapping work and merge time.

Up to two feedback requests follow the initial extraction **per chunk**. Every
candidate remains available even if checks fail. A truncated answer with recovered
schema-valid records stays partial and is flagged for finer splitting, rather
than spending a correction request on an empty schema patch.
Schema-valid output ends the loop immediately. Ambiguity and source-coverage
findings remain advisory and do not trigger retries. Unparseable responses and
schema-invalid records share the same maximum of two correction requests.

`completed_with_issues` means the workflow finished with unresolved findings. A
`partial` result or an unparseable raw response does not establish complete
extraction. Source citation coverage is a diagnostic, not proof of legal accuracy.

The original job also keeps `rules.json` and `rule_extraction_report.json` in backend
storage. The latter is available through the existing job-file API.
Individual results, reports and progress are additionally kept in the job's
`extraction-runs/<runId>/` directory. The timestamped total report embeds all chunk
reports, so it can be inspected without those internal files.

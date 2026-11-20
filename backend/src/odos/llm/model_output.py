"""Reading the model's answer, and preserving an unusable answer for diagnosis.

WHY A MALFORMED ANSWER USED TO FAIL A WHOLE EXTRACTION. The answer is one JSON document of 10k-20k tokens holding every
record. `json.loads` accepts it only if all of it is valid: one defect anywhere (an unescaped quote inside German text,
a missing comma, a comment, prose after the JSON that contains a brace) made the whole answer unusable, every record was
lost with it, and the answer itself was discarded, so the cause could not be found afterwards.

Structured output (Bedrock Converse `outputConfig.textFormat`, JSON schema) would make the answer parseable by
construction, but it accepts only a subset of JSON Schema (no recursive schemas, no `oneOf`/`not`, no numeric bounds,
`additionalProperties: false` on every object, at most 12 optional properties in all; AWS user guide "Structured
outputs"). The Rule JSON schema needs all of these (recursive predicates and requirement expressions, `oneOf` branches,
many optional properties), so it cannot be passed as is, and the schema is not to be changed. Instead:

* `parse_model_output` is conservative: the answer is used only if it is exactly a JSON value, or a JSON value with
  surrounding text (a code fence, a sentence before or after). It never edits the JSON. If that fails it raises
  `OutputParseError`, which carries the position of the defect (never the text) and the records that are complete JSON
  objects before the defect (`salvaged`), for the caller to decide about;
* `save_diagnostic` writes the unusable answer to a restricted file (directory 0700, file 0600, newest
  `DIAGNOSTICS_KEPT` kept) so it can be inspected; logs carry only its ID, length and hash.

Whatever is recovered is only a proposal: every record still goes through provenance rewrite, repair, checks and schema
validation in `odos.llm.rule_extraction`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("odos.llm.model_output")

DIAGNOSTICS_KEPT = 20
_FENCE = re.compile(r"^\s*```(?:json)?\s*\n(.*?)\n\s*```\s*$", re.DOTALL)
# never in a diagnostic file, whatever the model wrote: Bedrock API keys ("ABSK..."), AWS access key IDs, bearer tokens
_SECRETS = re.compile(r"ABSK[A-Za-z0-9+/=]{16,}|\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|(?i:bearer)\s+[A-Za-z0-9._~+/=-]{16,}")


class OutputParseError(ValueError):
    """The answer is not usable JSON. `reason` and `line`/`column` locate the defect; `salvaged` are the complete
    record objects before it. No part of the answer's text is in the message."""

    def __init__(self, reason: str, *, line: int | None = None, column: int | None = None, salvaged: list | None = None):
        where = f" at line {line}, column {column}" if line is not None else ""
        super().__init__(f"{reason}{where}")
        self.reason, self.line, self.column, self.salvaged = reason, line, column, salvaged or []


@dataclass
class ParsedOutput:
    rules: list[Any]
    mode: str  # "exact": the answer is the JSON; "embedded": JSON with text around it (ignored)
    ignored_chars: int = 0  # characters around the JSON that were ignored (their content is not kept)
    notes: list[str] = field(default_factory=list)


def _rules_of(data: Any) -> list | None:
    rules = data.get("rules") if isinstance(data, dict) else data
    return rules if isinstance(rules, list) else None


def parse_model_output(text: str) -> ParsedOutput:
    """The `rules` list of `{"rules": [...]}` (a bare list is tolerated). Raises `OutputParseError`."""
    candidate = text.strip()
    if m := _FENCE.match(candidate):
        candidate = m.group(1).strip()
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as first:
        error: json.JSONDecodeError = first
    else:
        rules = _rules_of(data)
        if rules is None:
            raise OutputParseError('the answer is JSON but not an object with a "rules" list')
        return ParsedOutput(rules, "exact", len(text.strip()) - len(candidate))

    decoder = json.JSONDecoder()
    starts = [i for i in (candidate.find("{"), candidate.find("[")) if i >= 0]
    if starts:
        start = min(starts)
        try:
            data, end = decoder.raw_decode(candidate, start)
        except json.JSONDecodeError as e:
            error = e
        else:
            rules = _rules_of(data)
            if rules is not None:
                ignored = start + len(candidate) - end
                return ParsedOutput(rules, "embedded", ignored, [f"{ignored} characters of text around the JSON were ignored"])
    raise OutputParseError(error.msg, line=error.lineno, column=error.colno, salvaged=_salvage(candidate, decoder))


def _salvage(text: str, decoder: json.JSONDecoder) -> list:
    """The complete JSON objects at the start of the `rules` array, up to the first that does not parse."""
    m = re.search(r'"rules"\s*:\s*\[', text)
    if not m:
        return []
    position, records = m.end(), []
    while True:
        while position < len(text) and text[position] in " \t\r\n,":
            position += 1
        if position >= len(text) or text[position] != "{":
            return records
        try:
            record, position = decoder.raw_decode(text, position)
        except json.JSONDecodeError:
            return records
        records.append(record)


# ── diagnostics ───────────────────────────────────────────────────────────────────────────────────────────────────────


def redact(text: str, secrets: tuple[str, ...] = ()) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return _SECRETS.sub("***", text)


def save_diagnostic(directory: Path, *, text: str, error: str, metadata: dict, secrets: tuple[str, ...] = (),
                    keep: int = DIAGNOSTICS_KEPT) -> str:
    """Write an unusable answer to `directory` (created 0700; the file is 0600) and return its diagnostic ID. The
    answer is model output about the document and stays on the server: it is never logged or served by the API."""
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    diagnostic_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:12]}"
    body = redact(text, secrets)
    record = {"diagnosticId": diagnostic_id, "error": error, **metadata, "responseChars": len(text),
              "responseSha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "response": body}
    path = directory / f"{diagnostic_id}.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        json.dump(record, out, ensure_ascii=False, indent=2)
    for old in sorted(directory.glob("*.json"))[:-keep] if keep > 0 else []:
        old.unlink(missing_ok=True)
    log.warning("unusable model answer kept as diagnostic %s (%d characters, sha256 %s): %s", diagnostic_id, len(text),
                record["responseSha256"][:16], error)
    return diagnostic_id


def default_diagnostics_dir(environ: dict | None = None) -> Path:
    """ODOS_LLM_DIAGNOSTICS_DIR, else a private folder in the user's cache (never inside the repository)."""
    env = os.environ if environ is None else environ
    configured = (env.get("ODOS_LLM_DIAGNOSTICS_DIR") or "").strip()
    return Path(configured) if configured else Path.home() / ".cache" / "odos" / "llm-diagnostics"

"""Routing: document type -> suggested processing mode. Separate from classification.

A manual override is always allowed; it is recorded and mismatches are explained, never blocked."""

from __future__ import annotations

from pydantic import BaseModel, Field

from odos.classification.model import ClassificationResult, DocumentType as D
from odos.parsing.profiles import structured_modes

MODE_FOR_TYPE: dict[D, str] = {
    D.GERMAN_LAW: "german_law",
    D.GERMAN_MODEL_REGULATION: "german_law",  # keeps document_type = german_model_regulation
    D.EU_REGULATION: "eu_legislation",
    D.EU_DIRECTIVE: "extract_only",  # not routed to the regulation parser until compatibility is verified
    D.TECHNICAL_STANDARD: "extract_only",  # Custom JSON not implemented yet
    D.UNKNOWN: "extract_only",
}
STRUCTURED = set(structured_modes())  # every registered legal profile produces a structure


class RoutingDecision(BaseModel):
    document_type: str | None = None
    suggested_mode: str | None = None
    chosen_mode: str
    manual_override: bool = False
    warnings: list[str] = Field(default_factory=list)


def route(result: ClassificationResult | None, requested_mode: str | None = None) -> RoutingDecision:
    """Without a request: the suggestion. With one: the request, flagged as override when it differs."""
    suggested = result.suggested_processing_mode if result else None
    chosen = requested_mode or suggested or "extract_only"
    warns: list[str] = []
    override = result is not None and requested_mode is not None and requested_mode != suggested
    if result is not None and override:
        t = result.document_type
        if chosen in STRUCTURED:
            if MODE_FOR_TYPE[t] != chosen:
                warns.append(f"Manual override: the document was classified as {t.value}, which normally uses '{MODE_FOR_TYPE[t]}'. "
                             f"Mode '{chosen}' may produce an empty or misleading structure.")  # fmt: skip
            else:
                warns.append(f"Manual override of the suggestion ('{suggested}') because the classification was not confident enough.")
            if t == D.EU_DIRECTIVE and chosen == "eu_legislation":
                warns.append("EU directives were not verified against the EU regulation parser.")
        else:
            warns.append("Manual override: extraction only; no legal structure will be produced.")
    return RoutingDecision(document_type=result.document_type.value if result else None, suggested_mode=suggested,
                           chosen_mode=chosen, manual_override=override, warnings=warns)  # fmt: skip

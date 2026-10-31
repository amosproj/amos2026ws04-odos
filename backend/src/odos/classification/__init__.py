"""Document classification and routing (heuristic, rule-based; no LLM, no network)."""

from odos.classification.classifier import classify_lines
from odos.classification.model import ClassificationResult, DocumentType, Evidence
from odos.classification.router import RoutingDecision, route
from odos.classification.text_source import lines_from_docling, lines_from_pdf

__all__ = ["classify_lines", "ClassificationResult", "DocumentType", "Evidence", "RoutingDecision", "route",
           "lines_from_docling", "lines_from_pdf"]

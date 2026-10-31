"""The universal parsing engine: one lifecycle (`engine`) for every legal profile (`profiles`).

`parse_document` is the public entry point; see Documentation/parsing.md for the stages, the profiles and how to add
one.
"""

from __future__ import annotations

from pathlib import Path

from odos.document_model import DocumentModel


def parse_document(path: Path, mode: str) -> DocumentModel:
    """Parse a Docling JSON file with the profile of `mode` ("german_law", "eu_legislation") through the shared
    lifecycle. An unknown mode is a ValueError; nothing is auto-detected."""
    from odos.parsing.engine import parse  # imported here: the profiles must stay importable without the engine
    from odos.parsing.profiles import get

    return parse(Path(path), get(mode))

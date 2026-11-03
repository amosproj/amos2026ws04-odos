"""Synthetic test documents (original text, freely redistributable): always available, no partner PDF needed."""

from pathlib import Path

import pytest
import synthetic_eu
import synthetic_german

from odos.parsing import parse_document


@pytest.fixture(scope="session")
def synthetic_eu_raw_json(tmp_path_factory) -> Path:
    """A synthetic EU regulation in Docling's JSON shape."""
    return synthetic_eu.write(tmp_path_factory.mktemp("synthetic_eu"))


@pytest.fixture(scope="session")
def synthetic_eu_model(synthetic_eu_raw_json):
    return parse_document(synthetic_eu_raw_json, "eu_legislation")


@pytest.fixture(scope="session")
def synthetic_german_raw_json(tmp_path_factory) -> Path:
    """A synthetic German law with a generated PDF, hence real PDF text-layer evidence."""
    return synthetic_german.write(tmp_path_factory.mktemp("synthetic_german"))


@pytest.fixture(scope="session")
def synthetic_german_model(synthetic_german_raw_json):
    return parse_document(synthetic_german_raw_json, "german_law")

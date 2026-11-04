"""The profile registry: one `LegalProfile` per supported kind of legislation (see `profiles.base`).

Adding a profile = one module declaring a `LegalProfile` plus its recognizer, registered in `PROFILES`. The shared
engine (`parsing.engine`), sentences, TOC normalization, the public JSON exporter and the pipeline read the
profile; none of them branches on a profile name.
"""

from __future__ import annotations

from odos.parsing.profiles.base import LegalProfile, TocVocabulary
from odos.parsing.profiles.eu_legislation import EU_LEGISLATION
from odos.parsing.profiles.german_law import GERMAN_LAW

PROFILES: dict[str, LegalProfile] = {p.mode: p for p in (GERMAN_LAW, EU_LEGISLATION)}

__all__ = ["PROFILES", "LegalProfile", "TocVocabulary", "for_legal_system", "for_model", "get", "structured_modes"]


def get(mode) -> LegalProfile:
    """The profile of a processing mode ("german_law", "eu_legislation"); unknown modes are an error."""
    try:
        return PROFILES[str(mode)]
    except KeyError:
        raise ValueError(f"{mode!r} is not a parser profile (known: {', '.join(PROFILES)})") from None


def for_model(model) -> LegalProfile:
    """The profile that produced `model` (`DocumentModel.profile`; None = German-law parser, as stored historically)."""
    for p in PROFILES.values():
        if p.model_profile == model.profile:
            return p
    raise ValueError(f"document model profile {model.profile!r} is not known (known: {', '.join(PROFILES)})")


def for_legal_system(system: str) -> LegalProfile:
    """The profile of a public JSON `legalSystem` ("de", "eu")."""
    for p in PROFILES.values():
        if p.legal_system == system:
            return p
    raise KeyError(system)


def structured_modes() -> tuple[str, ...]:
    """Processing modes that produce a legal structure (all registered profiles)."""
    return tuple(PROFILES)

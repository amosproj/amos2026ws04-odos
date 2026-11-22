"""V2: project-scope exclusions from the team's supplied German Excel list.

This is not a legal applicability decision. Only explicit 'Raus' rows are applied;
all partial/keep rows stay in full. Policies are limited to the two identified documents.
"""
from odos.llm_input.common import prune_document

POLICY_SOURCE = "ODOS_LLM_Ausschlussliste_Deutsch_Aktualisiert(1).xlsx"
EU_ARTICLES = {"12", *map(str, range(26, 43)), "44", "47", "48", "50", "53"}
MBO_SECTIONS = {"24", "52", "54", "56", "57", "65", "65a", "65b", "65c", "65d", "69", "70", "71", "84"}


def policy_for(document):
    identity = str(document.get("id", "")).lower()
    title = str(document.get("title", "")).lower()
    number = (document.get("identifiers") or {}).get("documentNumber")
    if (identity == "verordnung-2023-1230" or number == "2023/1230") and document.get("documentType") == "eu_regulation":
        return "eu-machinery-2023-1230"
    if identity == "mbo" and "musterbauordnung" in title:
        return "musterbauordnung"
    return None


def apply_applicability(document):
    policy = policy_for(document)

    def exclude(node):
        kind, number = node.get("type"), str(node.get("number", "")).lower()
        if policy == "eu-machinery-2023-1230" and kind == "article" and number in EU_ARTICLES:
            return "Excel exclusion: administrative/institutional provision outside ODOS checking scope"
        if policy == "musterbauordnung":
            if kind == "section" and number in MBO_SECTIONS:
                return "Excel exclusion: professional qualifications, administration or penalties"
            if kind == "annex" and number == "1":
                return "Excel exclusion: Anlage 1, professional training requirements"
        return None

    result, removed = prune_document(document, exclude)
    return result, {"policy": policy, "source": POLICY_SOURCE, "removed": removed}

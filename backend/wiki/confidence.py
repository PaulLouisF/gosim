"""
Confidence scoring engine.
Every source gets a final_confidence score from 0.0 to 1.0.
Score determines how the agent uses and presents information.
"""
from models.schemas import ConfidenceTier

# Domain credibility lookup
DOMAIN_SCORES: dict[str, float] = {
    # Tier 1 — peer-reviewed / authoritative
    "pubmed.ncbi.nlm.nih.gov": 0.97,
    "nejm.org": 0.97,
    "thelancet.com": 0.97,
    "nature.com": 0.95,
    "science.org": 0.95,
    "arxiv.org": 0.88,
    "jstor.org": 0.90,
    "britannica.com": 0.85,
    "wikipedia.org": 0.72,
    # Tier 2 — institutional
    ".gov": 0.88,
    ".edu": 0.85,
    ".org": 0.68,
    # Tier 3 — general web
    "medium.com": 0.45,
    "substack.com": 0.42,
    "reddit.com": 0.35,
    "quora.com": 0.30,
    # Default for unknown domains
    "_default": 0.50,
}


def get_domain_score(url: str) -> float:
    if not url:
        return 0.60  # uploaded file — assume reasonable
    for domain, score in DOMAIN_SCORES.items():
        if domain in url:
            return score
    return DOMAIN_SCORES["_default"]


def compute_corroboration(source_content: str, other_sources: list[str]) -> float:
    """
    Simple corroboration: fraction of other sources that share key terms.
    For hackathon: keyword overlap is sufficient.
    """
    if not other_sources:
        return 0.5
    words = set(source_content.lower().split())
    scores = []
    for other in other_sources:
        other_words = set(other.lower().split())
        overlap = len(words & other_words) / max(len(words), 1)
        scores.append(min(overlap * 5, 1.0))  # scale up
    return sum(scores) / len(scores)


def compute_final_confidence(credibility: float, corroboration: float) -> float:
    """Weighted combination: credibility 60%, corroboration 40%."""
    return round(credibility * 0.6 + corroboration * 0.4, 3)


def get_confidence_tier(score: float) -> ConfidenceTier:
    if score >= 0.80:
        return ConfidenceTier.high
    elif score >= 0.50:
        return ConfidenceTier.medium
    elif score >= 0.20:
        return ConfidenceTier.low
    else:
        return ConfidenceTier.discard


def get_confidence_caveat(tier: ConfidenceTier, topic: str) -> str:
    """Returns spoken caveat for non-high confidence answers."""
    if tier == ConfidenceTier.medium:
        return f"Based on a single source about {topic}, which hasn't been corroborated yet — "
    elif tier == ConfidenceTier.low:
        return f"⚠️ This comes from a low-confidence source about {topic}. Treat with caution: "
    return ""

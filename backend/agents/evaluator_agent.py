"""
Evaluator Agent: filters sources by confidence tier.
Discarded sources are logged but never silently dropped.
"""
from models.schemas import Source, ConfidenceTier
from wiki.manager import append_log


def evaluate_sources(sources: list[Source]) -> dict:
    """Split sources into tiers. Returns dict with usable and discarded sources."""
    usable = [s for s in sources if s.confidence_tier != ConfidenceTier.discard]
    discarded = [s for s in sources if s.confidence_tier == ConfidenceTier.discard]

    for s in discarded:
        append_log(f"discard | {s.title} | reason: {s.flagged_reason}")

    return {
        "high": [s for s in usable if s.confidence_tier == ConfidenceTier.high],
        "medium": [s for s in usable if s.confidence_tier == ConfidenceTier.medium],
        "low": [s for s in usable if s.confidence_tier == ConfidenceTier.low],
        "discarded": discarded,
        "usable": usable,
    }


def summarize_evaluation(evaluated: dict) -> str:
    """Human-readable evaluation summary for reasoning panel."""
    h = len(evaluated["high"])
    m = len(evaluated["medium"])
    l = len(evaluated["low"])
    d = len(evaluated["discarded"])
    return (f"{h} high-confidence, {m} medium, {l} low-confidence sources accepted. "
            f"{d} discarded.")

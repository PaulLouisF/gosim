"""Answer a user question from compiled wiki content using GLM (no thinking overhead)."""
import re
from services.zai_client import zai_complete

_MODEL = "glm-5.1"

_SYSTEM = (
    "You are Sensei. Answer in EXACTLY 2-3 complete sentences. "
    "Use only the wiki content provided. "
    "No thinking, no analysis, no meta-commentary, no bullet points. "
    "Just the answer sentences. Stop after 3 sentences."
)

# Two examples so the model sees the expected direct-answer pattern
_EXAMPLES = (
    "Wiki: Insulin therapy replaces the insulin the pancreas can no longer produce. "
    "Basal-bolus regimens combine long-acting and rapid-acting insulin. "
    "HbA1c below 7% reduces complication risk.\n"
    "Q: How is insulin managed?\n"
    "Answer: Insulin therapy uses a basal-bolus regimen, combining long-acting insulin "
    "for overnight needs with rapid-acting doses at meals. "
    "The target HbA1c is below 7% to reduce complication risk. (Insulin Therapy)\n\n"
    "Wiki: The heart has four chambers: two atria and two ventricles. "
    "The left ventricle pumps oxygenated blood to the body.\n"
    "Q: How does the heart work?\n"
    "Answer: The heart has four chambers — two atria that receive blood and two ventricles that pump it. "
    "The left ventricle sends oxygenated blood to the body. (Heart Anatomy)"
)

# Phrases that signal the model is writing meta-commentary — cut from here onwards
_CUT_TRIGGERS = (
    "i need to", "i should", "the source appears", "based on the content",
    "let me synthesize", "to summarize", "in summary", "i will now",
    "i'll provide", "i can now", "let me craft", "i'll write",
)


def _prep_context(wiki_context: str) -> str:
    """Strip markdown headings so the model sees plain prose, not section labels."""
    text = re.sub(r'^#{1,4}\s+.+$', '', wiki_context, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _clean(text: str) -> str:
    """Remove numbered prefixes, section labels, and meta-commentary."""
    lower = text.lower()
    for trigger in _CUT_TRIGGERS:
        idx = lower.find(trigger)
        if 0 < idx:
            text = text[:idx]
            lower = lower[:idx]

    # Strip numbered list prefixes: "1. " "2. " inline or at line start
    text = re.sub(r'(?:^|\s)\d+\.\s+', ' ', text)

    lines = text.split("\n")
    cleaned = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if re.match(r'^from the\b', line, re.IGNORECASE):
            continue
        line = re.sub(r'^[A-Z][^:]{3,50}:\s+', '', line)
        line = line.strip('"\'')
        line = re.sub(r'^[-*]\s+', '', line)
        cleaned.append(line)

    text = " ".join(cleaned)
    return re.sub(r'  +', ' ', text).strip()


async def answer_query(question: str, wiki_context: str) -> str:
    context = _prep_context(wiki_context)
    prompt = (
        f"{_EXAMPLES}\n\n"
        f"Wiki: {context}\n\n"
        f"Q: {question}\n"
        f"Answer:"
    )
    result = await zai_complete(prompt, system=_SYSTEM, max_tokens=600,
                                temperature=0.1, model=_MODEL)
    return _clean(result)

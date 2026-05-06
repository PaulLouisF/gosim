"""
Compiler Agent: the heart of the Karpathy LLM Wiki pattern.
Reads raw sources, writes structured wiki pages.
Uses MiniMax for rich, well-structured content generation.
"""
import asyncio
import json
import re
from services.minimax_client import minimax_complete
from wiki.manager import write_wiki_page, read_wiki_page
from wiki.confidence import get_confidence_tier
from models.schemas import Source, ConfidenceTier

PLANNER_PROMPT = """You are a knowledge architect.

The user wants to learn about: {topic}

Analyze this topic and return a JSON study plan:
{{
  "concepts": [
    {{
      "name": "concept name",
      "description": "one sentence",
      "depends_on": ["other concept name or null"]
    }}
  ],
  "estimated_pages": 5
}}

Return 4-8 concepts that together give complete understanding of the topic.
Order them from foundational to advanced.
Return ONLY valid JSON. No preamble."""

COMPILER_PROMPT = """You are a knowledge compiler writing a wiki page.

Topic: {topic}
Concept: {concept}
Related concepts: {related}

Source material:
{sources_text}

Output ONLY the raw markdown for the wiki page — no JSON wrapper, no preamble, no reasoning, no checklist.
Start immediately with the concept title as a level-2 heading.

Use this exact structure:
## {concept}

### Overview
[2-3 sentence definition using only information from the source material]

### Key Facts
[dense, well-organised paragraphs using ## / ### subheadings as needed; 300-600 words total]

### Related Concepts
[1-2 sentences connecting to related topics using [[wikilinks]] like [[related concept]]]

Write 400-700 words total. Only state things supported by the source material."""

UPDATE_PROMPT = """You are updating an existing wiki page with new information.

Existing page:
{existing_content}

New source material:
{new_sources_text}

Output ONLY the complete updated markdown — no JSON wrapper, no preamble, no reasoning.
Start immediately with the first heading of the page.
Keep [[wikilinks]] intact. Incorporate new facts and correct outdated information."""


def _clean_wiki_content(text: str) -> str:
    """Strip reasoning preambles, JSON wrappers, and trailing review text from model output."""
    text = text.strip()

    # Extract content from JSON wrapper if model returned {"content": "...", ...}
    if text.startswith("{") or "```json" in text:
        # Try extracting a markdown/content field from JSON
        for key in ("markdown", "content", "wiki_content", "page"):
            pattern = rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)"'
            m = re.search(pattern, text, re.DOTALL)
            if m:
                text = m.group(1).replace("\\n", "\n").replace('\\"', '"').strip()
                break
        else:
            # Try stripping ```json fences
            text = re.sub(r"```(?:json)?\s*\{.*?\}\s*```", "", text, flags=re.DOTALL).strip()

    # Strip reasoning preamble — everything before the first markdown heading
    heading_match = re.search(r"^#{1,3} ", text, re.MULTILINE)
    if heading_match and heading_match.start() > 0:
        text = text[heading_match.start():]

    # Strip trailing review / verification paragraphs
    # These typically start with "I should verify", "Let me verify", "Note:", "I need to"
    text = re.sub(
        r"\n+(I should verify|Let me verify|I need to|Note that|I've connected|"
        r"I should note|Now let me|I'll also|Let me also|I should also)[^\n]*(\n[^\n#].*)*$",
        "", text, flags=re.IGNORECASE
    ).strip()

    return text


async def plan_concepts(topic: str) -> list[dict]:
    """Plan which concept pages to create for a topic."""
    prompt = PLANNER_PROMPT.format(topic=topic)
    response = await minimax_complete(prompt, max_tokens=1500)
    # Robustly extract the JSON object, tolerating prose / fences / truncation
    clean = re.sub(r"```(?:json)?", "", response).strip()
    match = re.search(r'\{.*\}', clean, re.DOTALL)
    if not match:
        # Fallback: generate 4 generic concept names from the topic
        return [{"name": f"{topic} — {suffix}", "description": "", "depends_on": []}
                for suffix in ("Overview", "Key Concepts", "Applications", "Details")]
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        # Attempt partial recovery: extract concept names with a simple regex
        names = re.findall(r'"name"\s*:\s*"([^"]+)"', clean)
        if names:
            return [{"name": n, "description": "", "depends_on": []} for n in names]
        return [{"name": topic, "description": "", "depends_on": []}]
    return data.get("concepts", [{"name": topic, "description": "", "depends_on": []}])


async def compile_concept_page(concept: str, topic: str,
                                sources: list[Source],
                                all_concepts: list[str]) -> str:
    """Compile a wiki page for a single concept."""
    sources_text_parts = []
    for s in sources:
        marker = ""
        if s.confidence_tier == ConfidenceTier.low:
            marker = "[LOW CONFIDENCE] "
        elif s.confidence_tier == ConfidenceTier.medium:
            marker = "[MEDIUM CONFIDENCE] "
        sources_text_parts.append(
            f"### {marker}{s.title}\n"
            f"URL: {s.url or s.file_path}\n"
            f"Confidence: {s.final_confidence:.2f}\n\n"
            f"{s.content_preview}\n"
        )

    related = [c for c in all_concepts if c != concept]

    prompt = COMPILER_PROMPT.format(
        topic=topic,
        concept=concept,
        related=", ".join(related[:5]),
        sources_text="\n---\n".join(sources_text_parts)
    )
    result = await minimax_complete(prompt, max_tokens=1000)
    return _clean_wiki_content(result)


async def update_concept_page(concept: str, existing_content: str,
                               new_sources: list[Source]) -> str:
    """Update an existing wiki page with new sources."""
    sources_text = "\n---\n".join([
        f"### {s.title}\n{s.content_preview}"
        for s in new_sources
    ])
    prompt = UPDATE_PROMPT.format(
        existing_content=existing_content,
        new_sources_text=sources_text
    )
    result = await minimax_complete(prompt, max_tokens=1000)
    return _clean_wiki_content(result)


async def compile_topic(topic: str, sources: list[Source],
                         evaluated: dict) -> list[dict]:
    """
    Full compilation pipeline for a topic.
    Returns list of created wiki pages with metadata.
    """
    concepts = await plan_concepts(topic)
    concept_names = [c["name"] for c in concepts]

    # Pre-read existing pages (fast, no I/O contention)
    existing_map = {c["name"]: read_wiki_page(c["name"]) for c in concepts}

    # Compile all pages in parallel
    async def _compile_one(concept_info: dict) -> tuple[str, str, bool]:
        concept = concept_info["name"]
        existing = existing_map[concept]
        if existing:
            content = await update_concept_page(concept, existing, evaluated["usable"])
        else:
            content = await compile_concept_page(
                concept, topic, evaluated["usable"], concept_names
            )
        return concept, content, existing is None

    results = await asyncio.gather(*[_compile_one(c) for c in concepts])

    if evaluated["usable"]:
        avg_conf = sum(s.final_confidence for s in evaluated["usable"]) / len(evaluated["usable"])
    else:
        avg_conf = 0.5
    tier = get_confidence_tier(avg_conf)

    created_pages = []
    for concept, content, is_new in results:
        file_path = write_wiki_page(concept, content, evaluated["usable"], avg_conf, tier)
        created_pages.append({
            "concept": concept,
            "file_path": file_path,
            "confidence": avg_conf,
            "tier": tier,
            "is_new": is_new,
        })

    return created_pages

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

Write a comprehensive wiki page for "{concept}" that:
1. Defines the concept clearly and precisely
2. Explains mechanisms, causes, or principles
3. Covers key facts, classifications, or variations
4. Connects to related concepts using [[wikilinks]] like [[related concept]]
5. Highlights what is most important to understand

Use markdown with clear headers (##, ###).
Be dense with information but readable.
Write 400-700 words.
Every important term that has its own concept page should be [[wikilinked]].

IMPORTANT: Only state things that are supported by the provided source material.
If sources conflict, note the contradiction explicitly."""

UPDATE_PROMPT = """You are updating an existing wiki page with new information.

Existing page:
{existing_content}

New source material:
{new_sources_text}

Update the page to incorporate new information:
- Add any new facts not already covered
- Update any outdated information
- Note any contradictions between old and new sources
- Keep [[wikilinks]] intact
- Update the confidence assessment if needed

Return the complete updated page content (no frontmatter)."""


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
    return await minimax_complete(prompt, max_tokens=1000)


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
    return await minimax_complete(prompt, max_tokens=1000)


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

"""
Note Agent: handles voice note and wiki-edit commands.
Detects which concept and section the note belongs to, then inserts or appends.
"""
import json
import re
from services.zai_client import zai_complete
from wiki.manager import append_note_to_page, insert_into_section, list_wiki_pages, write_wiki_page
from wiki.confidence import get_confidence_tier
from models.schemas import Source, ConfidenceTier
from datetime import datetime

PARSE_PROMPT = """Parse this wiki edit / note command:
"{note}"

Known wiki concepts: {concepts}

Return ONLY valid JSON:
{{
  "concept": "exact concept name from the list that this note belongs to, or null",
  "section": "exact section/paragraph name to insert into (e.g. 'Overview'), or null to append at end",
  "text_to_add": "the actual sentence or fact to add — clean prose, no meta-commentary"
}}"""


def _extract_json(text: str) -> dict:
    text = re.sub(r"```(?:json)?", "", text).strip()
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return {}


async def handle_note(note_content: str, topic: str = None) -> dict:
    """Route a note or wiki-edit command to the correct page and section."""
    pages = list_wiki_pages()
    concepts = [p["concept"] for p in pages]

    if not concepts:
        concept = topic or "General Notes"
        _create_notes_page(concept, note_content)
        return {"concept": concept, "created": True}

    prompt = PARSE_PROMPT.format(
        note=note_content,
        concepts=", ".join(concepts)
    )
    response = await zai_complete(
        prompt,
        system="You are a routing assistant. Return only valid JSON.",
        max_tokens=150
    )
    parsed = _extract_json(response)

    concept = parsed.get("concept") or topic
    section = parsed.get("section")
    text = parsed.get("text_to_add") or note_content

    if not concept:
        concept = topic or "General Notes"
        _create_notes_page(concept, text)
        return {"concept": concept, "created": True}

    if section:
        success = insert_into_section(concept, section, text)
    else:
        success = append_note_to_page(concept, text)

    return {"concept": concept, "section": section, "appended": success}


def _create_notes_page(concept: str, first_note: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    content = f"## Notes\n\n> **Note ({timestamp}):** {first_note}\n> *Source: voice_note*\n"
    dummy_source = Source(
        id="voice_note",
        title="Voice Note",
        credibility_score=0.85,
        corroboration_score=0.5,
        final_confidence=0.85,
        confidence_tier=ConfidenceTier.high,
        scraped_at=datetime.now().isoformat(),
        content_preview=first_note[:200]
    )
    write_wiki_page(concept, content, [dummy_source], 0.85, ConfidenceTier.high)

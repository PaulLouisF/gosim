"""
Note Agent: handles voice note commands.
Detects which concept the note belongs to and appends it.
"""
import json
from services.zai_client import zai_complete
from wiki.manager import append_note_to_page, list_wiki_pages, write_wiki_page
from wiki.confidence import get_confidence_tier
from models.schemas import Source, ConfidenceTier
from datetime import datetime

NOTE_ROUTER_PROMPT = """The user added a voice note: "{note}"

Known wiki concepts: {concepts}

Which concept does this note belong to?
Return ONLY valid JSON:
{{
  "concept": "exact concept name from the list, or null if none match",
  "create_new": true,
  "new_concept_name": "name for new concept if create_new is true, else null"
}}"""


async def handle_note(note_content: str, topic: str = None) -> dict:
    """Route a voice note to the correct wiki page."""
    pages = list_wiki_pages()
    concepts = [p["concept"] for p in pages]

    if not concepts:
        concept = topic or "General Notes"
        _create_notes_page(concept, note_content)
        return {"concept": concept, "created": True}

    prompt = NOTE_ROUTER_PROMPT.format(
        note=note_content,
        concepts=", ".join(concepts)
    )
    response = await zai_complete(
        prompt,
        system="You are a routing assistant. Return only valid JSON.",
        max_tokens=100
    )
    clean = response.strip()
    if clean.startswith("```"):
        clean = clean.split("```")[1]
        if clean.startswith("json"):
            clean = clean[4:]
    routing = json.loads(clean.strip())

    if routing.get("create_new") and routing.get("new_concept_name"):
        concept = routing["new_concept_name"]
        _create_notes_page(concept, note_content)
        return {"concept": concept, "created": True}
    elif routing.get("concept"):
        concept = routing["concept"]
        success = append_note_to_page(concept, note_content)
        return {"concept": concept, "appended": success}
    else:
        concept = topic or "General Notes"
        _create_notes_page(concept, note_content)
        return {"concept": concept, "created": True}


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

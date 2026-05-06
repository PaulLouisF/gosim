"""
Tutor Agent: Socratic questioning using GLM-Z1.
Reads ONLY from the compiled wiki — never from raw sources.
"""
import json
import re
import uuid
from services.zai_client import zai_complete
from services.minimax_client import minimax_complete
from wiki.manager import read_wiki_page, list_wiki_pages
from retrieval.rag import retrieve_from_wiki

def _parse_json(text: str, fallback: dict) -> dict:
    """Extract first JSON object from text, return fallback on failure."""
    # Strip thinking blocks before searching for JSON
    clean = re.sub(r"<think(?:ing)?>.*?</think(?:ing)?>", "", text, flags=re.DOTALL)
    clean = re.sub(r"<think(?:ing)?>.*$", "", clean, flags=re.DOTALL)
    clean = re.sub(r"```(?:json)?", "", clean).strip()
    match = re.search(r'\{.*\}', clean, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return fallback


TUTOR_SYSTEM = """You are Sensei — a brilliant, demanding tutor.

ABSOLUTE RULES:
1. NEVER give the answer directly. Ever.
2. Ask ONE question at a time.
3. If the student struggles, ask a SIMPLER leading question.
4. If the student answers correctly, go deeper or move to next concept.
5. Base every question ONLY on the provided wiki content.
6. Be direct and challenging. You care about real understanding, not comfort.
7. Speak in 1-3 sentences maximum."""

QUESTION_PROMPT = """Wiki content for this concept:
{wiki_content}

All known concepts: {known_concepts}

Generate ONE short Socratic question about "{concept}" that:
- Is under 15 words
- Tests understanding, not just recall
- Ends with a question mark

Return ONLY the question. No preamble."""

ASSESS_PROMPT = """Wiki content:
{wiki_content}

Question asked: {question}
Ideal answer (from wiki): {ideal_clues}
Student answered: {student_answer}

Scoring rules — be strict:
- "strong"  = correct and complete answer using the right concepts
- "partial" = shows SOME relevant knowledge but misses key details
- "missed"  = wrong, vague, nonsensical, joke, or does not address the question at all

Examples of "missed": "I don't know", "because I am dumb", "I have no idea", "idk", answers that are clearly unrelated.
Examples of "partial": answer is in the right direction but lacks key specifics.

Assess and return ONLY valid JSON:
{{
  "score": "strong|partial|missed",
  "concept_missed": "specific concept they got wrong or null if strong",
  "feedback_internal": "what specifically was wrong (used for study plan, not shown)",
  "followup_question": "Socratic follow-up question if partial/missed, else null"
}}"""

STUDY_PLAN_PROMPT = """Based on this quiz performance, generate a study plan.

Topic: {topic}
Performance:
{performance_summary}

Available wiki pages:
{wiki_pages}

Return ONLY valid JSON:
{{
  "overall_assessment": "2-3 sentence honest summary",
  "ready": true,
  "strong_concepts": ["concept1"],
  "gaps": [
    {{
      "concept": "concept name",
      "severity": "critical|moderate",
      "what_to_review": "specific aspect to focus on",
      "wiki_page": "exact wiki page filename to reread",
      "practice_question": "one targeted practice question",
      "estimated_minutes": 20
    }}
  ],
  "study_order": ["concept1"],
  "total_minutes": 60
}}"""

DEBRIEF_PROMPT = """You are Sensei giving a 60-second spoken end-of-session summary.

Topic: {topic}
Strong areas: {strong}
Critical gaps: {critical}
Moderate gaps: {moderate}
Ready: {ready}

Deliver an honest, direct verbal assessment in 4-6 sentences.
Sound like a senior expert who genuinely cares about mastery.
Be specific — name exact concepts. End with one clear instruction.
No bullet points. This will be spoken aloud."""


async def generate_question(concept: str, session_concepts: list[str]) -> dict:
    """Generate a Socratic question for a concept."""
    wiki_content = read_wiki_page(concept) or ""
    if not wiki_content:
        chunks = retrieve_from_wiki(concept, n=2)
        wiki_content = "\n\n".join([c["text"] for c in chunks])

    prompt = QUESTION_PROMPT.format(
        wiki_content=wiki_content[:1500],
        known_concepts=", ".join(session_concepts),
        concept=concept
    )
    raw = await zai_complete(
        prompt,
        system=TUTOR_SYSTEM,
        max_tokens=800,
        temperature=0.3,
        model="minimax-m2"
    )
    # Extract just the question sentence
    questions = re.findall(r'[^.!?\n]+\?', raw)
    question_text = questions[-1].strip() if questions else raw.strip()
    # Safety fallback — never return an empty question
    if not question_text:
        question_text = f"Can you explain the key mechanism behind {concept}?"
    return {
        "id": str(uuid.uuid4())[:8],
        "concept": concept,
        "text": question_text,
        "wiki_content": wiki_content[:1000],
        "is_main": True,
        "is_followup": False,
    }


async def assess_answer(question: dict, student_answer: str) -> dict:
    """Assess a student's answer and generate follow-up if needed."""
    prompt = ASSESS_PROMPT.format(
        wiki_content=question["wiki_content"],
        question=question["text"],
        ideal_clues=question["wiki_content"][:500],
        student_answer=student_answer
    )
    response = await zai_complete(
        prompt,
        system="You are a precise assessor. Return only valid JSON.",
        max_tokens=500,
        strip=False,
    )
    return _parse_json(response, {
        "score": "partial",
        "concept_missed": None,
        "feedback_internal": "Could not parse assessment",
        "followup_question": None
    })


async def generate_study_plan(topic: str, gaps: list[dict]) -> dict:
    """Generate a personalized study plan from quiz gaps."""
    performance = "\n".join([
        f"- {g['concept']}: {g['score']}"
        + (f" (missed: {g.get('concept_missed', 'N/A')})" if g['score'] != 'strong' else "")
        for g in gaps
    ])
    pages = list_wiki_pages()
    wiki_pages_list = "\n".join([f"- {p['concept']} ({p['tier']})" for p in pages])

    prompt = STUDY_PLAN_PROMPT.format(
        topic=topic,
        performance_summary=performance or "No quiz data yet.",
        wiki_pages=wiki_pages_list or "No pages yet."
    )
    response = await minimax_complete(prompt, max_tokens=1500)
    return _parse_json(response, {
        "overall_assessment": "Study plan generation failed.",
        "ready": False,
        "strong_concepts": [],
        "gaps": [],
        "study_order": [],
        "total_minutes": 0
    })


async def generate_debrief(topic: str, plan: dict) -> str:
    """Generate a spoken debrief."""
    critical = [g["concept"] for g in plan.get("gaps", []) if g["severity"] == "critical"]
    moderate = [g["concept"] for g in plan.get("gaps", []) if g["severity"] == "moderate"]

    prompt = DEBRIEF_PROMPT.format(
        topic=topic,
        strong=", ".join(plan.get("strong_concepts", ["none"])),
        critical=", ".join(critical) if critical else "none",
        moderate=", ".join(moderate) if moderate else "none",
        ready=plan.get("ready", False)
    )
    return await zai_complete(prompt, max_tokens=200)

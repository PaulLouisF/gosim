"""
Orchestrator: detects intent, routes to appropriate agent.
Streams reasoning steps to frontend via WebSocket.
"""
import json
import re
from typing import Optional
from services.zai_client import zai_complete
from models.schemas import Intent, IntentResult

INTENT_SYSTEM = """You are an intent classifier. Reply with ONLY a JSON object — no prose, no markdown, no explanation.

JSON schema (fill in the values):
{"intent":"...","topic":null,"note_content":null,"source_ref":null,"config_key":null,"config_value":null,"confidence":0.9}

Intent values (pick exactly one):
- research   → user wants to LEARN a new topic ("teach me about X", "I want to learn X", "tell me about X")
- query      → user wants to ASK a question to the agent ("what is X?", "explain X", "how does X work", "I want to ask questions", "I have a question")
- quiz       → user wants the AGENT to test THEM ("quiz me", "test me", "ask me questions", "examine me")
- add_note   → user wants to save a note ("add a note: ...", "remember that", "note this")
- upload     → user mentions uploading a file
- study_plan → user asks what they should study or review ("what should I study?", "give me a study plan")
- review_sources → user wants to see sources ("show sources", "review sources", "what are your sources")
- remove_source  → user wants to delete a source ("remove that source", "discard X")
- open_source    → user wants to open a document
- configure  → user changes a setting ("set sources to 8", "use advanced search")
- end_session → user ends the session ("bye", "done", "end session")

KEY DISTINCTIONS:
- "I want to ask questions" or "I have questions" → query (user asks agent)
- "quiz me" or "test me" or "ask me questions" → quiz (agent asks user)
- "tell me about X" or "I want to learn X" → research (only when X is a real topic)
- Never classify as research if no real topic is mentioned

topic field: extract only if a real subject/domain is mentioned, else null"""


_KEYWORD_MAP = [
    (["quiz me", "test me", "ask me questions", "examine me", "i want you to quiz",
      "question me", "give me a quiz", "start a quiz", "start quiz"], "quiz"),
    (["add a note", "note this", "note:", "remember that", "i want to remember",
      "save this", "take note"], "add_note"),
    (["review sources", "show sources", "my sources", "what are your sources",
      "list sources", "show my sources"], "review_sources"),
    (["study plan", "what should i study", "what to review", "what to focus on",
      "help me study", "give me a plan"], "study_plan"),
    (["remove source", "delete source", "discard source", "remove that source"], "remove_source"),
    (["open source", "open document", "open file"], "open_source"),
    (["bye", "goodbye", "end session", "i'm done", "that's all"], "end_session"),
]


def _keyword_intent(utterance: str) -> Optional[str]:
    lower = utterance.lower()
    for keywords, intent in _KEYWORD_MAP:
        if any(kw in lower for kw in keywords):
            return intent
    return None


def _extract_json(text: str) -> dict:
    """Extract the first JSON object from text, tolerating prose around it."""
    text = text.strip()
    # Strip markdown fences
    text = re.sub(r"```(?:json)?", "", text).strip()
    # Find first { ... }
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        return json.loads(match.group())
    raise ValueError(f"No JSON object found in: {text!r}")


async def detect_intent(utterance: str, known_topics: list[str]) -> IntentResult:
    # Fast-path: keyword matching before hitting the LLM
    fast_intent = _keyword_intent(utterance)
    if fast_intent:
        return IntentResult(
            intent=fast_intent,
            topic=None,
            note_content=utterance if fast_intent == "add_note" else None,
            source_ref=None,
            config_key=None,
            config_value=None,
            confidence=0.95,
        )

    context = (f"Known topics already in wiki: "
               f"{', '.join(known_topics) if known_topics else 'none yet'}")
    prompt = f"{context}\n\nClassify this message: \"{utterance}\""
    response = await zai_complete(prompt, system=INTENT_SYSTEM, max_tokens=200, temperature=0.1)

    try:
        data = _extract_json(response)
    except (ValueError, json.JSONDecodeError):
        # Fallback: if it looks like a question use query, otherwise research
        q_words = ("what", "how", "why", "when", "who", "where", "?", "ask", "question")
        is_question = any(w in utterance.lower() for w in q_words)
        data = {
            "intent": "query" if is_question else "research",
            "topic": None if is_question else utterance,
            "note_content": None,
            "source_ref": None,
            "config_key": None,
            "config_value": None,
            "confidence": 0.5,
        }

    # Ensure required fields have defaults
    data.setdefault("topic", utterance if data.get("intent") in ("research", "query") else None)
    data.setdefault("note_content", None)
    data.setdefault("source_ref", None)
    data.setdefault("config_key", None)
    data.setdefault("config_value", None)
    data.setdefault("confidence", 0.8)

    return IntentResult(**data)

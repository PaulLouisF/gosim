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

JSON schema:
{"intent":"...","topic":null,"note_content":null,"source_ref":null,"config_key":null,"config_value":null,"confidence":0.9}

Intent values (pick exactly one):
- research   → user wants to ADD NEW knowledge ("teach me", "I want to learn", "research X", "find out about X")
- query      → user wants to GET AN ANSWER from existing knowledge ("explain X", "what is X", "how does X work", "describe X")
- quiz       → user wants the AGENT to test THEM ("quiz me", "test me", "ask me questions")
- add_note   → user wants to save a note ("add a note: ...", "remember that")
- upload     → user mentions uploading a file
- study_plan → user asks what they should study
- review_sources → user wants to see sources
- remove_source  → user wants to delete a source
- open_source    → user wants to open a document
- configure  → user changes a setting
- end_session → user ends the session

CRITICAL RULES:
- "explain X", "what is X", "how does X work", "describe X", "tell me about X" → ALWAYS query
- "I want to learn X", "teach me X", "research X", "find information about X" → research
- If the topic is already in the known wiki topics list → prefer query over research
- Never classify as research if the message is phrased as a question

topic field: extract the subject being asked about, else null"""


# Patterns that clearly indicate a question / explanation request → query
_QUERY_STARTS = (
    "what is", "what are", "what was", "what were",
    "how does", "how do", "how did", "how is", "how are",
    "why is", "why are", "why does", "why do",
    "explain", "describe", "can you explain", "can you describe",
    "tell me about", "tell me what", "tell me how",
    "could you explain", "help me understand",
)

# Patterns that clearly mean "go research a new topic" → research
_RESEARCH_STARTS = (
    "i want to learn", "i want to understand", "teach me about",
    "research ", "find information", "look up", "search for",
    "i'd like to learn", "i would like to learn",
    "create a wiki", "build a wiki", "make a wiki",
    "create wiki", "build wiki", "update wiki", "rebuild wiki",
    "add a page", "create a page",
    "add to the wiki", "add to wiki", "add information",
    "add info about", "ingest",
)

# Words that force research intent even if the topic already exists in the wiki
_FORCE_RESEARCH_WORDS = {"create", "build", "rebuild", "remake", "regenerate"}

_KEYWORD_MAP = [
    (["quiz me", "test me", "ask me questions", "ask me some questions",
      "examine me", "i want you to quiz", "question me", "give me a quiz",
      "start a quiz", "start quiz", "quiz me on", "quiz me about",
      "ask me about", "test my understanding", "check my understanding",
      "test my knowledge", "check my knowledge", "assess my knowledge",
      "i want to be tested", "i want to be quizzed",
      "generate a quiz", "generate quiz", "please generate a quiz",
      "generate questions", "please generate questions", "give me questions",
      "begin a quiz", "begin quiz", "launch a quiz", "run a quiz"], "quiz"),
    (["add a note", "note this", "note:", "remember that", "i want to remember",
      "save this", "take note",
      "add in the paragraph", "add to the page", "add to the wiki page",
      "i want you to add", "please add", "can you add",
      "add that", "add a sentence", "add the following",
      "in the wiki", "in the page", "in topic"], "add_note"),
    (["review sources", "show sources", "my sources", "what are your sources",
      "list sources", "show my sources"], "review_sources"),
    (["study plan", "what should i study", "what to review", "what to focus on",
      "help me study", "give me a plan", "summary of what i need to learn",
      "what did i get wrong", "what do i need to work on",
      "summarize my mistakes", "summarize my results",
      "what were my mistakes", "based on my answers"], "study_plan"),
    (["remove source", "delete source", "discard source", "remove that source"], "remove_source"),
    (["open source", "open document", "open file"], "open_source"),
    (["bye", "goodbye", "end session", "i'm done", "that's all"], "end_session"),
    # Quiz answer fallbacks — if these reach the router, activeQuestion was null;
    # safest response is to advance to the next quiz question rather than research
    (["i don't know", "i dont know", "i do not know", "no idea", "not sure",
      "skip", "pass", "next question", "i'm not sure", "im not sure",
      "skip this", "skip question", "move on"], "quiz"),
]


def _keyword_intent(utterance: str) -> Optional[str]:
    lower = utterance.lower().strip()

    # Check explicit non-query/research keywords first
    for keywords, intent in _KEYWORD_MAP:
        if any(kw in lower for kw in keywords):
            return intent

    # Semantic quiz detection — catches any phrasing with quiz/test/question words
    # directed at the user, without requiring exact phrases
    _QUIZ_NOUNS = {"quiz", "test", "question", "questions", "exam",
                   "examine", "assess", "challenge", "practice", "drill"}
    _QUIZ_ACTIONS = {"generate", "create", "give", "ask", "start",
                     "begin", "do", "run", "make", "fire"}
    if any(w in lower for w in _QUIZ_NOUNS):
        # Must be directed at self or be a generation request
        if re.search(r'\b(me|myself|my|us)\b', lower) or \
           any(a in lower for a in _QUIZ_ACTIONS):
            return "quiz"

    # Explicit question / explanation request → query
    if any(lower.startswith(p) or f" {p} " in lower for p in _QUERY_STARTS):
        return "query"

    # Explicit new-topic research request → research
    if any(lower.startswith(p) for p in _RESEARCH_STARTS):
        return "research"

    return None


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"```(?:json)?", "", text).strip()
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        return json.loads(match.group())
    raise ValueError(f"No JSON object found in: {text!r}")


async def detect_intent(utterance: str, known_topics: list[str]) -> IntentResult:
    # Check for inline user-provided content: "add to wiki about X: [long text]"
    # If the message contains a colon followed by 300+ chars of text, treat as research with raw content
    colon_match = re.search(r':\s*(.{300,})', utterance, re.DOTALL)
    if colon_match:
        raw_content = colon_match.group(1).strip()
        topic_part = utterance[:colon_match.start()].strip()
        topic_match = re.search(r'\b(?:about|on|regarding|for)\s+(.+?)$', topic_part, re.IGNORECASE)
        extracted_topic = topic_match.group(1).strip() if topic_match else topic_part
        return IntentResult(
            intent="research",
            topic=extracted_topic,
            raw_content=raw_content,
            note_content=None, source_ref=None, config_key=None, config_value=None,
            confidence=0.95,
        )

    # Fast-path: keyword / pattern matching before hitting the LLM
    fast_intent = _keyword_intent(utterance)
    if fast_intent:
        topic = None
        if fast_intent in ("research", "query"):
            topic = utterance
        elif fast_intent == "quiz":
            # Extract "about X" / "on X" topic if present
            m = re.search(r'\b(?:about|on|regarding)\s+(.+?)(?:\s+to\s+|\s+for\s+|$)', utterance, re.IGNORECASE)
            topic = m.group(1).strip() if m else None
        return IntentResult(
            intent=fast_intent,
            topic=topic,
            note_content=utterance if fast_intent == "add_note" else None,
            source_ref=None,
            config_key=None,
            config_value=None,
            confidence=0.95,
        )

    # LLM classification for ambiguous cases
    context = (f"Known topics already in wiki: "
               f"{', '.join(known_topics) if known_topics else 'none yet'}")
    prompt = f"{context}\n\nClassify this message: \"{utterance}\""
    response = await zai_complete(prompt, system=INTENT_SYSTEM, max_tokens=150, temperature=0.0)

    try:
        data = _extract_json(response)
    except (ValueError, json.JSONDecodeError):
        q_words = ("what", "how", "why", "when", "who", "where", "?", "explain", "describe")
        is_question = any(w in utterance.lower() for w in q_words)
        data = {
            "intent": "query" if is_question else "research",
            "topic": utterance,
            "note_content": None,
            "source_ref": None,
            "config_key": None,
            "config_value": None,
            "confidence": 0.5,
        }

    # Key safeguard: if LLM says "research" but the topic is already in the wiki → query
    # Exception: bypass if the user explicitly said "create / build / rebuild"
    lower_utt = utterance.lower()
    forced_research = any(w in lower_utt for w in _FORCE_RESEARCH_WORDS)
    if data.get("intent") == "research" and known_topics and not forced_research:
        topic_lower = (data.get("topic") or utterance).lower()
        for kt in known_topics:
            if kt.lower() in topic_lower or any(w in topic_lower for w in kt.lower().split()):
                data["intent"] = "query"
                break

    data.setdefault("topic", utterance if data.get("intent") in ("research", "query") else None)
    data.setdefault("note_content", None)
    data.setdefault("source_ref", None)
    data.setdefault("config_key", None)
    data.setdefault("config_value", None)
    data.setdefault("confidence", 0.8)

    return IntentResult(**data)


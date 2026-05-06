from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from enum import Enum


class Intent(str, Enum):
    research = "research"
    query = "query"
    quiz = "quiz"
    add_note = "add_note"
    upload = "upload"
    study_plan = "study_plan"
    review_sources = "review_sources"
    remove_source = "remove_source"
    open_source = "open_source"
    configure = "configure"
    end_session = "end_session"


class ConfidenceTier(str, Enum):
    high = "high"       # 0.80-1.00 — used freely
    medium = "medium"   # 0.50-0.79 — used with qualification
    low = "low"         # 0.20-0.49 — used but flagged
    discard = "discard" # 0.00-0.19 — logged but not used


class AnswerScore(str, Enum):
    strong = "strong"
    partial = "partial"
    missed = "missed"


class Source(BaseModel):
    id: str
    url: Optional[str] = None
    file_path: Optional[str] = None
    title: str
    domain: Optional[str] = None
    credibility_score: float
    corroboration_score: float
    final_confidence: float
    confidence_tier: ConfidenceTier
    scraped_at: str
    content_preview: str
    flagged_reason: Optional[str] = None


class WikiPage(BaseModel):
    concept: str
    file_path: str
    confidence: float
    confidence_tier: ConfidenceTier
    sources: List[Source]
    last_updated: str
    content_preview: str


class IntentResult(BaseModel):
    intent: Intent
    topic: Optional[str] = None
    note_content: Optional[str] = None
    source_ref: Optional[str] = None
    config_key: Optional[str] = None
    config_value: Optional[Any] = None
    confidence: float
    raw_content: Optional[str] = None  # user-pasted text to ingest directly


class ReasoningStep(BaseModel):
    type: str    # "orchestrator"|"research"|"evaluate"|"compile"|"tutor"|"note"
    message: str
    detail: Optional[str] = None
    status: str  # "running"|"done"|"warning"|"error"


class SessionConfig(BaseModel):
    num_sources: int = 5
    search_depth: str = "basic"   # "basic" | "advanced"
    speak_reasoning: bool = False


class TTSRequest(BaseModel):
    text: str
    voice: str = "en-US-Neural"


class VoiceMessage(BaseModel):
    session_id: str
    transcript: str


class AnswerRequest(BaseModel):
    session_id: str
    question_id: str
    answer: str


class NoteRequest(BaseModel):
    session_id: str
    note_content: str
    topic: Optional[str] = None

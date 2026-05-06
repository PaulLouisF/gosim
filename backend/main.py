"""
FastAPI application.
WebSocket for real-time reasoning stream.
REST endpoints for all agent operations.
"""
import uuid
import os
import traceback
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse
from dotenv import load_dotenv
load_dotenv()


def hv(text: str) -> str:
    """Sanitize a string for use as an HTTP header value (latin-1, no newlines)."""
    if not text:
        return ""
    text = text.replace("\r", " ").replace("\n", " ")
    return text.encode("latin-1", errors="replace").decode("latin-1")

import re
from wiki.manager import (init_vault, list_wiki_pages, read_wiki_page,
                           delete_wiki_page, delete_source_from_page,
                           append_log, get_index_content, rebuild_index,
                           WIKI_PATH)
from orchestrator.router import detect_intent
from agents.research_agent import research_topic, ingest_uploaded_file, create_source_from_text
from agents.evaluator_agent import evaluate_sources, summarize_evaluation
from agents.compiler_agent import compile_topic
from agents.tutor_agent import generate_question, assess_answer, generate_study_plan, generate_debrief
from agents.note_agent import handle_note
from agents.answer_agent import answer_query
from retrieval.rag import index_wiki, retrieve_from_wiki
from services.speechmatics_tts import speak
from services.zai_client import zai_complete
from models.schemas import (VoiceMessage, AnswerRequest, NoteRequest,
                             TTSRequest, SessionConfig)

init_vault()
# Rebuild index with summaries so queries work immediately after restart
try:
    rebuild_index()
except Exception:
    pass

app = FastAPI(title="Sensei Wiki API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Text", "X-Pages", "X-Sources", "X-Question-Id", "X-Concept", "X-Score"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch all unhandled exceptions and return a CORS-safe JSON error response."""
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)},
        headers={"Access-Control-Allow-Origin": "*"},
    )


# ── Session store ─────────────────────────────────────────────────────────────
sessions: dict[str, dict] = {}


# ── WebSocket Manager ─────────────────────────────────────────────────────────
class WSManager:
    def __init__(self):
        self.connections: dict[str, WebSocket] = {}

    async def connect(self, session_id: str, ws: WebSocket):
        await ws.accept()
        self.connections[session_id] = ws

    def disconnect(self, session_id: str):
        self.connections.pop(session_id, None)

    async def send(self, session_id: str, data: dict):
        ws = self.connections.get(session_id)
        if ws:
            try:
                await ws.send_json(data)
            except Exception:
                pass


ws_manager = WSManager()


async def emit(session_id: str, step_type: str, message: str,
               detail: str = None, status: str = "running"):
    await ws_manager.send(session_id, {
        "event": "reasoning",
        "step": {"type": step_type, "message": message,
                 "detail": detail, "status": status}
    })


# ── WebSocket endpoint ────────────────────────────────────────────────────────
@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await ws_manager.connect(session_id, websocket)
    try:
        while True:
            await websocket.receive_text()  # keep alive
    except WebSocketDisconnect:
        ws_manager.disconnect(session_id)


# ── Session management ────────────────────────────────────────────────────────
@app.post("/api/session/start")
async def start_session():
    session_id = str(uuid.uuid4())[:8]
    sessions[session_id] = {
        "config": SessionConfig(),
        "topic": None,
        "gaps": [],
        "questions": [],
        "question_index": 0,
        "sources": [],
        "quiz_queue": [],     # concepts remaining in active quiz
        "quiz_answered": 0,   # main questions answered so far
        "quiz_total": 0,      # total main questions in this quiz
    }
    return {"session_id": session_id}


@app.get("/api/session/{session_id}/config")
async def get_config(session_id: str):
    s = sessions.get(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    return s["config"].dict()


@app.put("/api/session/{session_id}/config")
async def update_config(session_id: str, config: SessionConfig):
    s = sessions.get(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    s["config"] = config
    return {"updated": True}


# ── Main voice interaction ────────────────────────────────────────────────────
@app.post("/api/session/{session_id}/message")
async def handle_message(session_id: str, msg: VoiceMessage):
    """Main entry point for all voice messages."""
    s = sessions.get(session_id)
    if not s:
        raise HTTPException(404, "Session not found")

    try:
        return await _handle_message_inner(session_id, s, msg.transcript)
    except Exception as exc:
        traceback.print_exc()
        err_text = f"Internal error: {str(exc)}"
        return JSONResponse(
            status_code=500,
            content={"detail": err_text},
            headers={
                "Access-Control-Allow-Origin": "*",
                "X-Text": hv("Something went wrong on my end. Check the backend logs."),
            },
        )


async def _handle_message_inner(session_id: str, s: dict, transcript: str) -> Response:
    known_topics = list_wiki_pages()
    known_concept_names = [p["concept"] for p in known_topics]

    await emit(session_id, "orchestrator", "Detecting intent...", transcript)
    intent_result = await detect_intent(transcript, known_concept_names)
    await emit(session_id, "orchestrator",
               f"Intent: {intent_result.intent}",
               f"Topic: {intent_result.topic}", "done")

    # ── RESEARCH ──────────────────────────────────────────────────────────────
    if intent_result.intent == "research":
        topic = intent_result.topic or transcript
        s["topic"] = topic
        cfg = s["config"]

        await emit(session_id, "orchestrator",
                   f"Planning research on: {topic}",
                   f"Searching {cfg.num_sources} sources, depth={cfg.search_depth}")

        await emit(session_id, "research", "Activating ResearchAgent...",
                   f"Querying Tavily for '{topic}'")
        if intent_result.raw_content:
            # User pasted raw text — use it as a source directly, skip Tavily
            sources = [create_source_from_text(topic, intent_result.raw_content)]
            await emit(session_id, "research", "Using user-provided content as source", None, "done")
        else:
            sources = await research_topic(topic, cfg.num_sources, cfg.search_depth)
            await emit(session_id, "research", f"Found {len(sources)} sources", None, "done")

        await emit(session_id, "evaluate", "Activating EvaluatorAgent...",
                   "Scoring source credibility and corroboration")
        evaluated = evaluate_sources(sources)
        summary = summarize_evaluation(evaluated)
        await emit(session_id, "evaluate", summary, None, "done")

        await emit(session_id, "compile", "Activating CompilerAgent...",
                   "Writing wiki pages to Obsidian vault")
        pages = await compile_topic(topic, sources, evaluated)
        s["sources"] = sources

        index_wiki()

        await emit(session_id, "compile",
                   f"Created {len(pages)} wiki pages",
                   "Obsidian vault updated", "done")

        await ws_manager.send(session_id, {
            "event": "wiki_updated",
            "pages": pages,
            "sources": [src.dict() for src in sources]
        })

        tts_text = f"Research complete. {len(pages)} pages ready."
        return Response(content=b"", media_type="audio/mpeg",
                        headers={"X-Text": hv(tts_text),
                                 "X-Pages": str(len(pages)),
                                 "X-Sources": str(len(evaluated["usable"]))})

    # ── QUERY ─────────────────────────────────────────────────────────────────
    elif intent_result.intent == "query":
        await emit(session_id, "orchestrator", f"Querying wiki for: {transcript}")

        # ── Karpathy LLM Wiki pattern ──────────────────────────────────────────
        # Step 1: read index.md to get the full catalog of pages + summaries
        index_content = get_index_content()

        if not index_content.strip() or "No pages yet" in index_content:
            msg_text = "No knowledge base yet. Tell me a topic to research first."
            return Response(content=b"", media_type="audio/mpeg",
                            headers={"X-Text": hv(msg_text)})

        # Step 2: ask the LLM which pages are relevant (fast lookup, no embeddings)
        PAGE_SELECT_SYSTEM = (
            "You are a wiki librarian. Given an index of wiki pages and a question, "
            "return ONLY a comma-separated list of the most relevant page filenames "
            "(without .md extension). Return at most 4 filenames. No explanation, no prose."
        )
        page_select_prompt = (
            f"Wiki index:\n{index_content}\n\n"
            f"Question: {transcript}\n\n"
            f"Return the filenames of the most relevant pages (comma-separated, no .md, no spaces around commas):"
        )
        selected_raw = await zai_complete(
            page_select_prompt, system=PAGE_SELECT_SYSTEM,
            max_tokens=80, temperature=0.0
        )
        # Strip any thinking/prose the model might prepend
        selected_raw = re.sub(r'(?i)^(thinking:|the most relevant|here are|pages?:).*?\n', '', selected_raw.strip())
        selected_names = [n.strip().strip('"\'') for n in selected_raw.split(",") if n.strip()]
        await emit(session_id, "orchestrator",
                   f"Reading pages: {', '.join(selected_names[:3])}")

        # Step 3: read the selected pages — cap each at 800 chars to keep prompt small
        context_parts = []
        confidences = []
        for name in selected_names[:3]:
            concept_guess = name.replace("_", " ")
            content = read_wiki_page(concept_guess)
            if not content:
                filepath = WIKI_PATH / (name + ".md")
                if filepath.exists():
                    content = filepath.read_text(encoding="utf-8")
            if content:
                body = re.sub(r'^---.*?---\s*', '', content, flags=re.DOTALL).strip()
                context_parts.append(f"## {concept_guess}\n\n{body[:800]}")
                conf_match = re.search(r'^confidence:\s*(.+)$', content, re.MULTILINE)
                if conf_match:
                    confidences.append(float(conf_match.group(1).strip()))

        # Fallback: if no pages found, load all pages (trimmed)
        if not context_parts:
            all_pages = list_wiki_pages()
            for p in all_pages:
                content = read_wiki_page(p["concept"])
                if content:
                    body = re.sub(r'^---.*?---\s*', '', content, flags=re.DOTALL).strip()
                    context_parts.append(f"## {p['concept']}\n\n{body[:600]}")
                    confidences.append(p["confidence"])

        context = "\n\n---\n\n".join(context_parts)

        # Step 4: answer via MiniMax (follows instructions reliably)
        full_answer = await answer_query(transcript, context)

        await emit(session_id, "orchestrator", "Answer ready", None, "done")
        return Response(content=b"", media_type="audio/mpeg",
                        headers={"X-Text": hv(full_answer)})

    # ── QUIZ ──────────────────────────────────────────────────────────────────
    elif intent_result.intent == "quiz":
        pages = list_wiki_pages()
        if not pages:
            msg_text = "No knowledge base yet. Tell me a topic to research first."
            return Response(content=b"", media_type="audio/mpeg",
                            headers={"X-Text": hv(msg_text)})

        # Filter to topic if specified ("quiz me about type 1 diabetes")
        quiz_topic = intent_result.topic
        if quiz_topic:
            lower_topic = quiz_topic.lower().strip()
            # Try exact substring match first (most precise)
            exact = [p for p in pages if lower_topic in p["concept"].lower()]
            if exact:
                pages = exact
            else:
                # Fall back: ALL non-trivial words must appear in concept name
                topic_words = [w for w in lower_topic.split() if len(w) > 2]
                broad = [p for p in pages if all(w in p["concept"].lower() for w in topic_words)]
                if broad:
                    pages = broad

        # Build a queue of 4 distinct concepts
        N = 4
        start = s["question_index"] % len(pages)
        concepts = [pages[(start + i) % len(pages)]["concept"] for i in range(N)]
        s["question_index"] += N

        # Store remaining concepts in queue; ask first one now
        first_concept = concepts[0]
        s["quiz_queue"] = concepts[1:]
        s["quiz_answered"] = 0
        s["quiz_total"] = N
        s["gaps"] = []  # reset gaps for fresh quiz session

        # Pre-generate all 4 questions in parallel — Q2/Q3/Q4 are ready instantly
        all_concept_names = [p["concept"] for p in pages]
        import asyncio as _asyncio
        await emit(session_id, "tutor", f"Generating {N} questions in parallel...")
        all_questions = list(await _asyncio.gather(*[
            generate_question(c, all_concept_names) for c in concepts
        ]))
        # Number them and store
        for i, q in enumerate(all_questions):
            q["quiz_number"] = i + 1
        s["questions"].extend(all_questions)
        s["quiz_queue"] = [q["id"] for q in all_questions[1:]]  # IDs of Q2..Q4
        s["quiz_answered"] = 0
        s["quiz_total"] = N
        s["gaps"] = []

        first_q = all_questions[0]
        await emit(session_id, "tutor", "Questions ready", None, "done")
        audio = await speak(first_q["text"])
        return Response(content=audio, media_type="audio/mpeg",
                        headers={"X-Text": hv(f"Question 1/{N}: {first_q['text']}"),
                                 "X-Question-Id": first_q["id"],
                                 "X-Concept": hv(first_concept)})

    # ── ADD NOTE ──────────────────────────────────────────────────────────────
    elif intent_result.intent == "add_note":
        note = intent_result.note_content or transcript
        await emit(session_id, "note", f"Adding note: {note[:60]}...")
        result = await handle_note(note, s.get("topic"))
        await emit(session_id, "note", f"Note added to: {result['concept']}", None, "done")
        await ws_manager.send(session_id, {"event": "wiki_updated"})
        msg_text = f"Note added to {result['concept']}."
        return Response(content=b"", media_type="audio/mpeg",
                        headers={"X-Text": hv(msg_text)})

    # ── STUDY PLAN ────────────────────────────────────────────────────────────
    elif intent_result.intent == "study_plan":
        topic = s.get("topic", "your topic")
        await emit(session_id, "tutor", "Generating study plan...")
        plan = await generate_study_plan(topic, s["gaps"])
        await emit(session_id, "tutor", "Study plan ready", None, "done")
        await ws_manager.send(session_id, {"event": "study_plan", "plan": plan})

        # Build a readable text synthesis — no TTS for long content
        strong = plan.get("strong_concepts", [])
        gaps = plan.get("gaps", [])
        lines = [plan.get("overall_assessment", "")]
        if strong:
            lines.append(f"Strong: {', '.join(strong)}.")
        if gaps:
            critical = [g["concept"] for g in gaps if g.get("severity") == "critical"]
            moderate = [g["concept"] for g in gaps if g.get("severity") == "moderate"]
            if critical:
                lines.append(f"Must review: {', '.join(critical)}.")
            if moderate:
                lines.append(f"Also review: {', '.join(moderate)}.")
            order = plan.get("study_order", [])
            if order:
                lines.append(f"Study order: {' → '.join(order)}.")
        synthesis = " ".join(l for l in lines if l)
        return Response(content=b"", media_type="audio/mpeg",
                        headers={"X-Text": hv(synthesis)})

    # ── REVIEW SOURCES ────────────────────────────────────────────────────────
    elif intent_result.intent == "review_sources":
        sources = s.get("sources", [])
        await ws_manager.send(session_id, {
            "event": "show_sources",
            "sources": [src.dict() for src in sources]
        })
        msg_text = (f"Showing {len(sources)} sources in the panel. "
                    f"Say 'remove' followed by the source name to delete one.")
        return Response(content=b"", media_type="audio/mpeg",
                        headers={"X-Text": hv(msg_text)})

    # ── REMOVE SOURCE ─────────────────────────────────────────────────────────
    elif intent_result.intent == "remove_source":
        ref = intent_result.source_ref or ""
        sources = s.get("sources", [])
        match = next((src for src in sources
                      if ref.lower() in src.title.lower()
                      or (src.url and ref.lower() in src.url.lower())), None)

        if match:
            pages = list_wiki_pages()
            removed_from = []
            for page in pages:
                url_ref = match.url or match.file_path or ""
                if url_ref and delete_source_from_page(page["concept"], url_ref):
                    removed_from.append(page["concept"])

            s["sources"] = [src for src in sources if src.id != match.id]

            index_wiki()

            await ws_manager.send(session_id, {
                "event": "source_removed",
                "source_id": match.id,
                "affected_pages": removed_from
            })

            msg_text = (f"Removed {match.title} and updated "
                        f"{len(removed_from)} wiki pages.")
        else:
            msg_text = f"I couldn't find a source matching '{ref}'. Try saying the exact title."

        return Response(content=b"", media_type="audio/mpeg",
                        headers={"X-Text": hv(msg_text)})
    elif intent_result.intent == "open_source":
        ref = intent_result.source_ref or ""
        sources = s.get("sources", [])
        match = next((src for src in sources
                      if ref.lower() in src.title.lower()), None)
        if match:
            await ws_manager.send(session_id, {
                "event": "open_source",
                "url": match.url,
                "file_path": match.file_path,
                "title": match.title
            })
            msg_text = f"Opening {match.title}."
        else:
            msg_text = "I couldn't find that source."

        return Response(content=b"", media_type="audio/mpeg",
                        headers={"X-Text": hv(msg_text)})

    # ── DEFAULT ───────────────────────────────────────────────────────────────
    else:
        fallback = ("I didn't understand that. You can say: learn about a topic, "
                    "quiz me, add a note, review sources, or ask me a question.")
        return Response(content=b"", media_type="audio/mpeg",
                        headers={"X-Text": hv(fallback)})


# ── Answer submission (quiz) ──────────────────────────────────────────────────
@app.post("/api/session/{session_id}/answer")
async def submit_answer(session_id: str, req: AnswerRequest):
    s = sessions.get(session_id)
    if not s:
        raise HTTPException(404)

    question = next((q for q in s["questions"] if q["id"] == req.question_id), None)
    if not question:
        raise HTTPException(404, "Question not found")

    assessment = await assess_answer(question, req.answer)
    is_main = question.get("is_main", True)
    is_followup = question.get("is_followup", False)

    s["gaps"].append({
        "concept": question["concept"],
        "score": assessment["score"],
        "concept_missed": assessment.get("concept_missed"),
        "question": question["text"]
    })

    await ws_manager.send(session_id, {
        "event": "answer_assessed",
        "score": assessment["score"],
        "concept": question["concept"],
        "concept_missed": assessment.get("concept_missed"),
        "gaps": s["gaps"]
    })

    # Count main questions answered
    if is_main:
        s["quiz_answered"] = s.get("quiz_answered", 0) + 1

    quiz_answered = s.get("quiz_answered", 0)
    quiz_total = s.get("quiz_total", 0)
    quiz_queue = s.get("quiz_queue", [])

    # Give one follow-up on missed/partial (only for main questions, not for follow-ups)
    followup_text = assessment.get("followup_question")
    if followup_text and is_main and not is_followup:
        followup_q = {
            "id": str(uuid.uuid4())[:8],
            "concept": question["concept"],
            "text": followup_text,
            "wiki_content": question.get("wiki_content", ""),
            "is_main": False,
            "is_followup": True,
        }
        s["questions"].append(followup_q)
        audio = await speak(followup_text)
        return Response(content=audio, media_type="audio/mpeg",
                        headers={"X-Text": hv(followup_text),
                                 "X-Score": assessment["score"],
                                 "X-Question-Id": followup_q["id"],
                                 "X-Concept": hv(question["concept"])})

    # Move to next pre-generated question
    if quiz_queue:
        next_id = quiz_queue.pop(0)
        s["quiz_queue"] = quiz_queue
        next_q = next((q for q in s["questions"] if q["id"] == next_id), None)
        if next_q:
            q_num = quiz_answered + 1
            audio = await speak(next_q["text"])
            return Response(content=audio, media_type="audio/mpeg",
                            headers={"X-Text": hv(f"Question {q_num}/{quiz_total}: {next_q['text']}"),
                                     "X-Score": assessment["score"],
                                     "X-Question-Id": next_q["id"],
                                     "X-Concept": hv(next_q["concept"])})

    # Quiz complete — generate synthesis
    if quiz_total > 0 and quiz_answered >= quiz_total:
        topic = s.get("topic", "the topic")
        plan = await generate_study_plan(topic, s["gaps"])
        await ws_manager.send(session_id, {"event": "study_plan", "plan": plan})

        strong = plan.get("strong_concepts", [])
        gaps = plan.get("gaps", [])
        correct = sum(1 for g in s["gaps"] if g["score"] == "strong")
        lines = [f"Quiz complete! {correct}/{quiz_total} correct."]
        lines.append(plan.get("overall_assessment", ""))
        if strong:
            lines.append(f"Strong: {', '.join(strong)}.")
        critical = [g["concept"] for g in gaps if g.get("severity") == "critical"]
        moderate = [g["concept"] for g in gaps if g.get("severity") == "moderate"]
        if critical:
            lines.append(f"Must review: {', '.join(critical)}.")
        if moderate:
            lines.append(f"Also review: {', '.join(moderate)}.")
        synthesis = " ".join(l for l in lines if l)

        # Reset quiz state
        s["quiz_queue"] = []
        s["quiz_total"] = 0
        s["quiz_answered"] = 0

        return Response(content=b"", media_type="audio/mpeg",
                        headers={"X-Text": hv(synthesis),
                                 "X-Score": assessment["score"]})

    # Fallback (single-question mode, no active quiz session)
    if assessment["score"] == "strong":
        response_text = "Correct."
        return Response(content=b"", media_type="audio/mpeg",
                        headers={"X-Text": hv(response_text),
                                 "X-Score": assessment["score"]})

    return {"score": assessment["score"]}


# ── TTS direct ────────────────────────────────────────────────────────────────
@app.post("/api/tts")
async def tts(req: TTSRequest):
    audio = await speak(req.text, req.voice)
    return Response(content=audio, media_type="audio/mpeg")


# ── File upload ───────────────────────────────────────────────────────────────
@app.post("/api/session/{session_id}/upload")
async def upload_file(session_id: str, file: UploadFile = File(...)):
    s = sessions.get(session_id)
    if not s:
        raise HTTPException(404)

    uploads_path = Path(os.getenv("UPLOADS_PATH", "./obsidian-vault/uploads"))
    uploads_path.mkdir(parents=True, exist_ok=True)
    file_path = uploads_path / file.filename

    with open(file_path, "wb") as f:
        f.write(await file.read())

    source = await ingest_uploaded_file(str(file_path), file.filename)
    s["sources"].append(source)

    await ws_manager.send(session_id, {
        "event": "file_uploaded",
        "source": source.dict()
    })

    return {"uploaded": True, "source": source.dict()}


# ── Wiki pages ────────────────────────────────────────────────────────────────
@app.get("/api/wiki/pages")
async def get_wiki_pages():
    return {"pages": list_wiki_pages()}


@app.get("/api/wiki/pages/{concept}")
async def get_wiki_page(concept: str):
    content = read_wiki_page(concept)
    if not content:
        raise HTTPException(404)
    return {"concept": concept, "content": content}


@app.delete("/api/wiki/pages/{concept}")
async def remove_wiki_page(concept: str):
    deleted = delete_wiki_page(concept)
    return {"deleted": deleted}


@app.get("/health")
async def health():
    return {"status": "ok"}

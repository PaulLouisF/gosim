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
    """Sanitize a string for use as an HTTP header value (no newlines, ASCII only)."""
    if not text:
        return ""
    return text.replace("\r", " ").replace("\n", " ").encode("ascii", errors="replace").decode("ascii")[:500]

from wiki.manager import (init_vault, list_wiki_pages, read_wiki_page,
                           delete_wiki_page, delete_source_from_page, append_log)
from orchestrator.router import detect_intent
from agents.research_agent import research_topic, ingest_uploaded_file
from agents.evaluator_agent import evaluate_sources, summarize_evaluation
from agents.compiler_agent import compile_topic
from agents.tutor_agent import generate_question, assess_answer, generate_study_plan, generate_debrief
from agents.note_agent import handle_note
from retrieval.rag import index_wiki, retrieve_from_wiki, should_use_rag
from services.speechmatics_tts import speak
from services.zai_client import zai_complete
from models.schemas import (VoiceMessage, AnswerRequest, NoteRequest,
                             TTSRequest, SessionConfig)

init_vault()

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
        "sources": []
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

        if should_use_rag():
            index_wiki()

        await emit(session_id, "compile",
                   f"Created {len(pages)} wiki pages",
                   "Obsidian vault updated", "done")

        await ws_manager.send(session_id, {
            "event": "wiki_updated",
            "pages": pages,
            "sources": [src.dict() for src in sources]
        })

        tts_text = (f"I've researched {topic} and built your knowledge base "
                    f"with {len(pages)} concept pages from "
                    f"{len(evaluated['usable'])} verified sources. "
                    f"Ask me anything, say quiz me, or add a note.")
        audio = await speak(tts_text)
        return Response(content=audio, media_type="audio/mpeg",
                        headers={"X-Text": hv(tts_text),
                                 "X-Pages": str(len(pages)),
                                 "X-Sources": str(len(evaluated["usable"]))})

    # ── QUERY ─────────────────────────────────────────────────────────────────
    elif intent_result.intent == "query":
        await emit(session_id, "orchestrator", f"Querying wiki for: {transcript}")

        if should_use_rag():
            chunks = retrieve_from_wiki(transcript, n=3)
            context = "\n\n".join([c["text"][:500] for c in chunks])
            min_conf = min([c["confidence"] for c in chunks], default=0.5)
        else:
            index = list_wiki_pages()
            relevant_pages = index[:5]
            context_parts = []
            for p in relevant_pages:
                content = read_wiki_page(p["concept"])
                if content:
                    context_parts.append(content[:400])
            context = "\n\n".join(context_parts)
            min_conf = min([p["confidence"] for p in relevant_pages], default=0.5)

        caveat = ""
        if min_conf < 0.50:
            caveat = "Note: some of my knowledge on this has low confidence. "
        elif min_conf < 0.80:
            caveat = "Based on moderately confident sources: "

        QUERY_SYSTEM = """You are Sensei, answering from your compiled wiki only.
Be precise and cite which concepts your answer draws from.
If the answer isn't in your wiki, say so explicitly — never hallucinate."""

        prompt = f"Wiki context:\n{context}\n\nQuestion: {transcript}"
        answer = await zai_complete(prompt, system=QUERY_SYSTEM, max_tokens=300)
        full_answer = caveat + answer

        await emit(session_id, "orchestrator", "Answer ready", None, "done")
        audio = await speak(full_answer)
        return Response(content=audio, media_type="audio/mpeg",
                        headers={"X-Text": hv(full_answer)})

    # ── QUIZ ──────────────────────────────────────────────────────────────────
    elif intent_result.intent == "quiz":
        pages = list_wiki_pages()
        if not pages:
            msg_text = "No knowledge base yet. Tell me a topic to research first."
            audio = await speak(msg_text)
            return Response(content=audio, media_type="audio/mpeg",
                            headers={"X-Text": hv(msg_text)})

        idx = s["question_index"] % len(pages)
        concept = pages[idx]["concept"]

        await emit(session_id, "tutor", f"Generating question on: {concept}")
        question = await generate_question(concept, [p["concept"] for p in pages])
        s["questions"].append(question)
        s["question_index"] += 1

        await emit(session_id, "tutor", "Question ready", None, "done")
        audio = await speak(question["text"])
        return Response(content=audio, media_type="audio/mpeg",
                        headers={"X-Text": hv(question["text"]),
                                 "X-Question-Id": question["id"],
                                 "X-Concept": concept})

    # ── ADD NOTE ──────────────────────────────────────────────────────────────
    elif intent_result.intent == "add_note":
        note = intent_result.note_content or transcript
        await emit(session_id, "note", f"Adding note: {note[:60]}...")
        result = await handle_note(note, s.get("topic"))
        await emit(session_id, "note", f"Note added to: {result['concept']}", None, "done")
        await ws_manager.send(session_id, {"event": "wiki_updated"})
        msg_text = f"Note added to {result['concept']}."
        audio = await speak(msg_text)
        return Response(content=audio, media_type="audio/mpeg",
                        headers={"X-Text": hv(msg_text)})

    # ── STUDY PLAN ────────────────────────────────────────────────────────────
    elif intent_result.intent == "study_plan":
        topic = s.get("topic", "your topic")
        await emit(session_id, "tutor", "Generating study plan...")
        plan = await generate_study_plan(topic, s["gaps"])
        debrief = await generate_debrief(topic, plan)
        await emit(session_id, "tutor", "Study plan ready", None, "done")
        await ws_manager.send(session_id, {"event": "study_plan", "plan": plan})
        audio = await speak(debrief)
        return Response(content=audio, media_type="audio/mpeg",
                        headers={"X-Text": hv(debrief)})

    # ── REVIEW SOURCES ────────────────────────────────────────────────────────
    elif intent_result.intent == "review_sources":
        sources = s.get("sources", [])
        await ws_manager.send(session_id, {
            "event": "show_sources",
            "sources": [src.dict() for src in sources]
        })
        msg_text = (f"Showing {len(sources)} sources in the panel. "
                    f"Say 'remove' followed by the source name to delete one.")
        audio = await speak(msg_text)
        return Response(content=audio, media_type="audio/mpeg",
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

            if should_use_rag():
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

        audio = await speak(msg_text)
        return Response(content=audio, media_type="audio/mpeg",
                        headers={"X-Text": hv(msg_text)})

    # ── OPEN SOURCE ───────────────────────────────────────────────────────────
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

        audio = await speak(msg_text)
        return Response(content=audio, media_type="audio/mpeg",
                        headers={"X-Text": hv(msg_text)})

    # ── DEFAULT ───────────────────────────────────────────────────────────────
    else:
        fallback = ("I didn't understand that. You can say: learn about a topic, "
                    "quiz me, add a note, review sources, or ask me a question.")
        audio = await speak(fallback)
        return Response(content=audio, media_type="audio/mpeg",
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

    response_text = None
    if assessment.get("followup_question"):
        response_text = assessment["followup_question"]
    elif assessment["score"] == "strong":
        response_text = "Correct. " + (assessment.get("feedback_internal", ""))

    if response_text:
        audio = await speak(response_text)
        return Response(content=audio, media_type="audio/mpeg",
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

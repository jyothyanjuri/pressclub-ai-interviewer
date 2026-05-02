import uuid
import json
import logging
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from agents.research_agent import run_research_agent
from agents.synthesis_agent import run_synthesis_agent
from services.transcriber import transcribe
from services.vapi_service import create_vapi_assistant
from services.storage import (
    save_briefing_doc,
    save_transcript,
    save_output,
    load_session,
    SESSION_DIR,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="PressClub AI Voice Interviewer", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")


def _decode_text(raw_bytes: bytes) -> str:
    for enc in ("utf-8", "gb18030", "big5"):
        try:
            return raw_bytes.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw_bytes.decode("utf-8", errors="replace")


# ── Request / Response models ───────────────────────────────────────────────

class StartInterviewRequest(BaseModel):
    session_id: str


class VapiWebhookPayload(BaseModel):
    type: str
    call: Optional[dict] = None
    transcript: Optional[str] = None
    artifact: Optional[dict] = None
    message: Optional[dict] = None


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.post("/research")
async def research(
    company_url: str = Form(...),
    linkedin_url: str = Form(""),
    transcript_file: Optional[UploadFile] = File(None),
    transcript_text: Optional[str] = Form(None),
):
    """
    Phase 0 + 1: ingest inputs, run research agent, return briefing_doc.json.
    """
    session_id = str(uuid.uuid4())

    # Resolve raw transcript
    if transcript_file and transcript_file.filename:
        raw_bytes = await transcript_file.read()
        suffix = Path(transcript_file.filename).suffix.lower()
        if suffix == ".txt":
            raw_transcript = _decode_text(raw_bytes)
        else:
            raw_transcript = await transcribe(raw_bytes, suffix)
    elif transcript_text:
        raw_transcript = transcript_text.strip()
    else:
        raw_transcript = ""

    try:
        briefing_doc = await run_research_agent(
            raw_transcript=raw_transcript,
            company_url=company_url,
            linkedin_url=linkedin_url,
        )
    except Exception as exc:
        logger.exception("Research agent failed")
        raise HTTPException(status_code=500, detail=str(exc))

    save_briefing_doc(session_id, briefing_doc)

    return JSONResponse({"session_id": session_id, "briefing_doc": briefing_doc})


@app.post("/start-interview")
async def start_interview(req: StartInterviewRequest):
    """
    Phase 2: create a Vapi assistant pre-loaded with the briefing doc.
    Returns assistant_id for the browser SDK.
    """
    session = load_session(req.session_id)
    if not session or "briefing_doc" not in session:
        raise HTTPException(status_code=404, detail="Session not found or briefing doc missing")

    try:
        assistant_id = await create_vapi_assistant(session["briefing_doc"])
    except Exception as exc:
        logger.exception("Vapi assistant creation failed")
        raise HTTPException(status_code=500, detail=str(exc))

    # Persist assistant_id so webhook can match it later
    session["assistant_id"] = assistant_id
    save_briefing_doc(req.session_id, session["briefing_doc"], extra={"assistant_id": assistant_id})

    return {"assistant_id": assistant_id, "session_id": req.session_id}


@app.post("/vapi-webhook")
async def vapi_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Phase 2 → 3: receive post-call transcript from Vapi, trigger synthesis.
    Accepts raw JSON to avoid Pydantic validation errors on unexpected Vapi fields.
    """
    payload = await request.json()

    # Vapi wraps everything under a "message" key
    msg = payload.get("message") or payload

    if msg.get("type") == "end-of-call-report":
        call = msg.get("call") or {}
        artifact = msg.get("artifact") or {}

        assistant_id = call.get("assistantId") or artifact.get("assistantId")

        # Transcript can be a plain string or reconstructed from messages array
        transcript_text = msg.get("transcript") or artifact.get("transcript") or ""
        if not transcript_text:
            messages = artifact.get("messages") or []
            lines = []
            for m in messages:
                role = m.get("role", "")
                text = m.get("message") or m.get("content") or ""
                if role in ("assistant", "user") and text:
                    label = "Journalist" if role == "assistant" else "Founder"
                    lines.append(f"{label}: {text}")
            transcript_text = "\n".join(lines)

        logger.info("Webhook — assistant_id=%s transcript_len=%d", assistant_id, len(transcript_text))

        session_id = _find_session_by_assistant(assistant_id)
        if session_id:
            save_transcript(session_id, transcript_text)
            background_tasks.add_task(_run_synthesis, session_id, transcript_text)
        else:
            logger.warning("No session found for assistant_id=%s", assistant_id)

    return {"status": "ok"}


@app.get("/results/{session_id}")
async def get_results(session_id: str):
    """
    Return scorecard, transcript, and output path for the results page.
    """
    session = load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    output_path = SESSION_DIR / session_id / "output.md"
    transcript_path = SESSION_DIR / session_id / "interview_transcript.txt"

    return {
        "session_id": session_id,
        "briefing_doc": session.get("briefing_doc"),
        "transcript": transcript_path.read_text(encoding="utf-8", errors="replace") if transcript_path.exists() else None,
        "output": output_path.read_text(encoding="utf-8", errors="replace") if output_path.exists() else None,
        "status": session.get("status", "pending"),
    }


# ── Custom LLM endpoint (Stretch Goal 1) ────────────────────────────────────

@app.post("/chat/completions")
async def custom_llm_completions(body: dict):
    """
    OpenAI-compatible endpoint Vapi calls when configured with a Custom LLM URL.
    Enables dynamic follow-up logic between turns.
    """
    import anthropic
    import os

    messages = body.get("messages", [])
    system = next((m["content"] for m in messages if m["role"] == "system"), "")
    conversation = [m for m in messages if m["role"] != "system"]

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=system,
        messages=conversation,
    )

    # Return in OpenAI-compatible format
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": response.content[0].text},
                "finish_reason": "stop",
            }
        ],
    }


# ── Helpers ──────────────────────────────────────────────────────────────────

def _find_session_by_assistant(assistant_id: Optional[str]) -> Optional[str]:
    if not assistant_id:
        return None
    # Since the same assistant is reused across sessions, find the MOST RECENT
    # session with this assistant_id that hasn't completed synthesis yet.
    matches = []
    for session_dir in SESSION_DIR.iterdir():
        meta_path = session_dir / "meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8", errors="replace"))
            if meta.get("assistant_id") == assistant_id:
                matches.append((session_dir.stat().st_mtime, session_dir.name))
    if not matches:
        return None
    # Return the most recently modified session
    matches.sort(reverse=True)
    return matches[0][1]


async def _run_synthesis(session_id: str, transcript: str):
    session = load_session(session_id)
    if not session:
        return
    try:
        output = await run_synthesis_agent(
            transcript=transcript,
            briefing_doc=session.get("briefing_doc", {}),
        )
        save_output(session_id, output)
        # Mark session complete
        meta_path = SESSION_DIR / session_id / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8", errors="replace")) if meta_path.exists() else {}
        meta["status"] = "complete"
        meta_path.write_text(json.dumps(meta, indent=2))
    except Exception:
        logger.exception("Synthesis agent failed for session %s", session_id)

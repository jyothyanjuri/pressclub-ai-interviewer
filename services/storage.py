"""
Storage Service

Saves all pipeline outputs locally under sessions/{session_id}/.
Structured for easy S3 migration: replace _write_local with _write_s3.
"""

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SESSION_DIR = Path("sessions")
SESSION_DIR.mkdir(exist_ok=True)


def save_briefing_doc(session_id: str, briefing_doc: dict, extra: Optional[dict] = None) -> None:
    session_path = _ensure_session(session_id)
    (session_path / "briefing_doc.json").write_text(
        json.dumps(briefing_doc, indent=2), encoding="utf-8"
    )
    meta = {"session_id": session_id, "status": "researched"}
    if extra:
        meta.update(extra)
    _write_meta(session_id, meta)
    logger.info("Saved briefing_doc for session %s", session_id)


def save_transcript(session_id: str, transcript: str) -> None:
    session_path = _ensure_session(session_id)
    (session_path / "interview_transcript.txt").write_text(transcript, encoding="utf-8")
    _merge_meta(session_id, {"status": "transcript_received"})
    logger.info("Saved transcript for session %s", session_id)


def save_output(session_id: str, output: str) -> None:
    session_path = _ensure_session(session_id)
    (session_path / "output.md").write_text(output, encoding="utf-8")
    _merge_meta(session_id, {"status": "complete"})
    logger.info("Saved output.md for session %s", session_id)


def save_audio_url(session_id: str, audio_url: str) -> None:
    """Store Vapi-provided audio URL so it can be downloaded or linked later."""
    session_path = _ensure_session(session_id)
    (session_path / "audio_url.txt").write_text(audio_url, encoding="utf-8")
    _merge_meta(session_id, {"audio_url": audio_url})


def load_session(session_id: str) -> Optional[dict]:
    """
    Load all available session data into a single dict.
    Returns None if session directory does not exist.
    """
    session_path = SESSION_DIR / session_id
    if not session_path.exists():
        return None

    result: dict = {}

    meta_path = session_path / "meta.json"
    if meta_path.exists():
        result.update(json.loads(meta_path.read_text(encoding="utf-8", errors="replace")))

    briefing_path = session_path / "briefing_doc.json"
    if briefing_path.exists():
        result["briefing_doc"] = json.loads(briefing_path.read_text(encoding="utf-8", errors="replace"))

    transcript_path = session_path / "interview_transcript.txt"
    if transcript_path.exists():
        result["transcript"] = transcript_path.read_text(encoding="utf-8", errors="replace")

    output_path = session_path / "output.md"
    if output_path.exists():
        result["output"] = output_path.read_text(encoding="utf-8", errors="replace")

    return result


# ── Internal helpers ──────────────────────────────────────────────────────────

def _ensure_session(session_id: str) -> Path:
    path = SESSION_DIR / session_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_meta(session_id: str, meta: dict) -> None:
    path = SESSION_DIR / session_id / "meta.json"
    path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _merge_meta(session_id: str, updates: dict) -> None:
    path = SESSION_DIR / session_id / "meta.json"
    existing = json.loads(path.read_text(encoding="utf-8", errors="replace")) if path.exists() else {}
    existing.update(updates)
    path.write_text(json.dumps(existing, indent=2), encoding="utf-8")

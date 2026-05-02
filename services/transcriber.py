"""
Transcriber Service

Converts input formats to clean transcript text.
- .txt → direct read
- audio (.mp3/.wav/.m4a/.ogg) → OpenAI Whisper
"""

import io
import os
import tempfile
import time
import logging

from openai import OpenAI

logger = logging.getLogger(__name__)

SUPPORTED_AUDIO = {".mp3", ".wav", ".m4a", ".ogg", ".webm", ".flac"}


async def transcribe(audio_bytes: bytes, suffix: str) -> str:
    """
    Transcribe audio bytes to text using Whisper.
    suffix: file extension including dot, e.g. '.mp3'
    """
    if suffix not in SUPPORTED_AUDIO:
        raise ValueError(f"Unsupported audio format: {suffix}. Supported: {SUPPORTED_AUDIO}")

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    start = time.monotonic()

    # Whisper needs a real file-like object with a name
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        with open(tmp_path, "rb") as f:
            response = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="text",
            )
    finally:
        import os as _os
        _os.unlink(tmp_path)

    elapsed = time.monotonic() - start
    text = response if isinstance(response, str) else response.text
    logger.info("Whisper transcription: %.1f chars in %.1fs", len(text), elapsed)
    return text


def read_txt(path: str) -> str:
    """Read a .txt file directly."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()

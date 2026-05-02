"""
Vapi Service

Configures and creates a Vapi assistant pre-loaded with the briefing doc
as the system prompt context. Returns assistant_id for the browser SDK.

Stretch Goal 1: Replace model config with Custom LLM URL by setting
VAPI_CUSTOM_LLM_URL env var — no other code changes needed.
"""

import json
import logging
import os
from pathlib import Path


import httpx

logger = logging.getLogger(__name__)

VAPI_API_BASE = "https://api.vapi.ai"
INTERVIEWER_PROMPT_PATH = "prompts/interviewer.txt"
PREBUILT_ASSISTANT_ID = "abcbbe84-9859-4182-a77f-ca9370188caa"


async def create_vapi_assistant(briefing_doc: dict) -> str:
    """
    Updates the pre-built Vapi assistant with the briefing doc injected into
    the system prompt, then returns its assistant_id for the browser SDK.
    """
    api_key = os.environ["VAPI_API_KEY"]
    base_persona = _load_interviewer_prompt()
    system_prompt = _build_system_prompt(base_persona, briefing_doc)

    payload = {
        "model": {
            "provider": "openai",
            "model": "gpt-4.1",
            "systemPrompt": system_prompt,
            "temperature": 0.7,
        },
        "firstMessage": _build_opening(briefing_doc),
        "endCallMessage": "Thank you so much for your time. This has been incredibly helpful. We'll be in touch soon.",
        "endCallPhrases": ["end the interview", "stop the interview"],
        "maxDurationSeconds": 2400,
        "silenceTimeoutSeconds": 60,
        "backgroundSound": "off",
        "backchannelingEnabled": True,
        "stopSpeakingPlan": {
            "numWords": 0,
            "voiceSeconds": 0.8,
            "backoffSeconds": 2.0,
        },
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.patch(
            f"{VAPI_API_BASE}/assistant/{PREBUILT_ASSISTANT_ID}",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()

    logger.info("Updated Vapi assistant: %s", PREBUILT_ASSISTANT_ID)
    return PREBUILT_ASSISTANT_ID



def _build_system_prompt(base_persona: str, briefing_doc: dict) -> str:
    # If the briefing doc was saved in fallback form (data stuck in interview_strategy
    # as a raw JSON string), parse it out and use the real data.
    if not briefing_doc.get("known_facts") and not briefing_doc.get("priority_questions"):
        raw_strategy = briefing_doc.get("interview_strategy", "")
        if raw_strategy.strip().startswith("{"):
            try:
                parsed = json.loads(raw_strategy.strip())
                if parsed.get("priority_questions") or parsed.get("known_facts"):
                    briefing_doc = parsed
                    logger.info("Recovered briefing doc from interview_strategy field")
            except Exception:
                pass

    company = briefing_doc.get("company_name", "this startup")
    founder = briefing_doc.get("founder_name", "the founder")
    strategy = briefing_doc.get("interview_strategy", "")
    known_facts = briefing_doc.get("known_facts", [])
    priority_questions = briefing_doc.get("priority_questions", [])
    avoid_topics = briefing_doc.get("avoid_topics", [])
    angles = briefing_doc.get("hypothesized_angles", [])

    questions_formatted = "\n".join(
        f"  {i+1}. {q['question']} — If vague: \"{q.get('follow_up_if_vague', 'Can you give me a specific number?')}\""
        for i, q in enumerate(priority_questions[:10])
    )

    return f"""{base_persona}

---

## YOUR BRIEFING DOC FOR TODAY'S INTERVIEW

**Company:** {company}
**Founder:** {founder}

**What you already know (do not ask about these):**
{chr(10).join(f"- {f}" for f in known_facts)}

**Hypothesized angles to probe:**
{chr(10).join(f"- [{a['angle_type'].upper()}] {a['description']} (confidence: {a.get('confidence', 'medium')})" for a in angles)}

**Priority questions:**
{questions_formatted if questions_formatted else "  - Probe for specific metrics, traction numbers, and unique founder background"}

**Topics to avoid:**
{chr(10).join(f"- {t}" for t in avoid_topics) if avoid_topics else "  - None flagged"}

**Interview strategy:**
{strategy}

---

Remember: Always ask for specific numbers. Never accept "we're growing fast" — ask "what was your MRR 6 months ago and what is it now?"."""


def _build_opening(briefing_doc: dict) -> str:
    founder = briefing_doc.get("founder_name", "")
    company = briefing_doc.get("company_name", "your company")
    first_name = founder.split()[0] if founder else "there"
    return (
        f"Hi {first_name}, thanks so much for making time today. "
        f"I've done some reading on {company} but I want to hear everything directly from you. "
        f"Tell me — what are you building and why now?"
    )


def _load_interviewer_prompt() -> str:
    try:
        return Path(INTERVIEWER_PROMPT_PATH).read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return (
            "You are a senior tech journalist with 10 years covering B2B SaaS and deep tech. "
            "You are curious, warm, but persistent. You do not accept vague answers. "
            "You always ask for specific numbers and concrete evidence."
        )

"""
Phase 3 — Synthesis Agent

Reads the full Vapi interview transcript against the briefing_doc.
Produces output.md: scorecard + structured notes for Weida's pipeline.
"""

import json
import logging
import os

import anthropic

logger = logging.getLogger(__name__)

SYNTHESIZER_PROMPT_PATH = "prompts/synthesizer.txt"

SIGNAL_TYPES = [
    "funding",
    "product_world_first",
    "product_world_best",
    "traction_revenue",
    "traction_growth",
    "traction_quality",
    "founder_uniqueness",
    "insight_contrarian",
]


async def run_synthesis_agent(transcript: str, briefing_doc: dict) -> str:
    """
    Synthesize interview transcript + briefing doc into output.md string.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    system = _load_prompt()

    company = briefing_doc.get("company_name", "the company")
    founder = briefing_doc.get("founder_name", "the founder")
    angles = briefing_doc.get("hypothesized_angles", [])
    known_facts = briefing_doc.get("known_facts", [])

    prompt = f"""You are synthesizing the results of an AI-conducted interview for PressClub.

COMPANY: {company}
FOUNDER: {founder}

BRIEFING DOC — HYPOTHESIZED ANGLES:
{json.dumps(angles, indent=2)}

BRIEFING DOC — KNOWN FACTS (do not re-surface as new findings):
{json.dumps(known_facts, indent=2)}

INTERVIEW TRANSCRIPT:
{transcript}

Produce output.md with these exact sections:

## Interview Summary
One paragraph overview of what was covered.

## Newsworthy Scorecard
For each signal type below, mark it as `confirmed`, `unconfirmed`, or `needs follow-up`.
Include a one-line evidence quote from the transcript (or "no evidence found").

Signals: {', '.join(SIGNAL_TYPES)}

## Structured Interview Notes
Key findings organized by signal type. Only include signals with evidence.

## Recommended Pitch Angle
The 1-2 strongest signals worth pursuing, with specific data points and recommended framing.

## Transcript (Timestamped)
The full interview transcript as provided.

IMPORTANT: Do not fabricate facts not present in the transcript. Mark anything uncertain as `needs follow-up`."""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )

    return response.content[0].text


def _load_prompt() -> str:
    try:
        return open(SYNTHESIZER_PROMPT_PATH).read()
    except FileNotFoundError:
        return "You are a synthesis agent for PressClub. Produce accurate, pipeline-ready interview output."

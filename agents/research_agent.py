"""
Phase 1 — Research Agent

Orchestrates all research sources and synthesizes a structured briefing_doc.json
that the Vapi interviewer agent uses as its interview strategy.
"""

import json
import logging
import os
import re
from typing import Any

import anthropic

from services.crawler_service import scrape_linkedin_profile
from services.website_reader import read_website

logger = logging.getLogger(__name__)

RESEARCH_PROMPT_PATH = "prompts/research.txt"

TOOLS = [
    {
        "name": "parse_transcript",
        "description": (
            "Extract key facts, claims, metrics, and statements from a sales call transcript. "
            "Returns a structured dict of what the founder said."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "transcript": {"type": "string", "description": "The raw sales call transcript text"},
            },
            "required": ["transcript"],
        },
    },
    {
        "name": "read_website",
        "description": (
            "Fetch and extract structured content from a company website URL. "
            "Returns product description, metrics, funding info, and customer names."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The company website URL"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "scrape_linkedin",
        "description": (
            "Backup source only — scrape a LinkedIn profile URL when one is provided. "
            "Returns founder name, role, company stage, work history, and education. "
            "Only call this tool if a LinkedIn URL was explicitly supplied."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The LinkedIn profile URL"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "synthesize_briefing",
        "description": (
            "Synthesize all gathered research into a structured briefing_doc.json. "
            "Apply the newsworthy angle framework and produce ranked interview questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "transcript_facts": {
                    "type": "object",
                    "description": "Facts extracted from the sales transcript",
                },
                "website_content": {
                    "type": "object",
                    "description": "Structured content from the company website",
                },
                "linkedin_profile": {
                    "type": "object",
                    "description": "Founder/company profile from LinkedIn",
                },
            },
            "required": ["transcript_facts", "website_content"],
        },
    },
]


async def run_research_agent(
    raw_transcript: str,
    company_url: str,
    linkedin_url: str = "",
) -> dict:
    """
    Orchestrates the full research pipeline via Claude tool use.
    Returns briefing_doc as a Python dict.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    system_prompt = _load_prompt()

    linkedin_instruction = (
        f"3. Call scrape_linkedin with: {linkedin_url} (backup enrichment — do this after steps 1 and 2)"
        if linkedin_url else
        "3. LinkedIn URL not provided — skip scrape_linkedin entirely"
    )

    user_message = f"""You are the research agent for PressClub.

PRIMARY sources (always use both):
1. Sales call transcript — the most important input, contains direct founder statements
2. Company website URL: {company_url}

BACKUP source:
{linkedin_instruction}

Your job:
1. Call parse_transcript with the transcript
2. Call read_website with the company URL
{linkedin_instruction}
{"4" if linkedin_url else "3"}. Call synthesize_briefing with all gathered results to produce the final briefing doc

The transcript and website are sufficient to produce a high-quality briefing doc.
If LinkedIn is available, use it to enrich founder background details only.

TRANSCRIPT:
{raw_transcript if raw_transcript else "(none provided)"}

Execute the steps now."""

    messages = [{"role": "user", "content": user_message}]

    # Accumulated data from tool calls
    transcript_facts: dict = {}
    website_content: dict = {}
    linkedin_profile: dict = {}
    briefing_doc: dict = {}

    # Agentic loop
    while True:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=system_prompt,
            tools=TOOLS,
            messages=messages,
        )

        # Append assistant turn
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason != "tool_use":
            break

        # Process tool calls
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue

            tool_name = block.name
            tool_input = block.input
            logger.info("Tool call: %s", tool_name)

            result = await _dispatch_tool(
                tool_name, tool_input,
                transcript_facts, website_content, linkedin_profile,
            )

            if tool_name == "parse_transcript":
                transcript_facts = result
            elif tool_name == "read_website":
                website_content = result
            elif tool_name == "scrape_linkedin":
                linkedin_profile = result
            elif tool_name == "synthesize_briefing":
                briefing_doc = result

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result),
            })

        messages.append({"role": "user", "content": tool_results})

    # If synthesize_briefing was called, return its output; otherwise fall back
    if briefing_doc:
        return briefing_doc

    # Last-resort: synthesize directly without tool loop
    logger.warning("synthesize_briefing tool was not called — running direct synthesis")
    return await _direct_synthesis(client, system_prompt, transcript_facts, website_content, linkedin_profile)


async def _dispatch_tool(
    name: str,
    inputs: dict,
    transcript_facts: dict,
    website_content: dict,
    linkedin_profile: dict,
) -> Any:
    if name == "parse_transcript":
        return _parse_transcript(inputs["transcript"])

    if name == "read_website":
        return await read_website(inputs["url"])

    if name == "scrape_linkedin":
        return await scrape_linkedin_profile(inputs["url"])

    if name == "synthesize_briefing":
        return _build_briefing_from_dicts(
            inputs.get("transcript_facts", transcript_facts),
            inputs.get("website_content", website_content),
            inputs.get("linkedin_profile", linkedin_profile),
        )

    return {"error": f"Unknown tool: {name}"}


def _parse_transcript(transcript: str) -> dict:
    """
    Extract structured facts from the raw transcript using Claude inline
    (not another agentic loop — just a single extraction call).
    """
    if not transcript:
        return {"facts": [], "metrics": [], "claims": [], "funding_mentions": []}

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": (
                    "Extract all facts, metrics, claims, and funding mentions from this transcript. "
                    "Return a JSON object with keys: facts (list), metrics (list), claims (list), "
                    "funding_mentions (list). Only include what is explicitly stated.\n\n"
                    f"TRANSCRIPT:\n{transcript}"
                ),
            }
        ],
    )
    raw = resp.content[0].text.strip()
    try:
        return _extract_json(raw)
    except ValueError:
        return {"facts": [raw], "metrics": [], "claims": [], "funding_mentions": []}


def _build_briefing_from_dicts(
    transcript_facts: dict,
    website_content: dict,
    linkedin_profile: dict,
) -> dict:
    """
    Use Claude tool_use to force structured JSON output — no parsing needed.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    system = _load_prompt()

    # Define a tool that Claude is forced to call — guarantees structured output
    output_tool = {
        "name": "return_briefing_doc",
        "description": "Return the completed briefing document for the AI interviewer.",
        "input_schema": {
            "type": "object",
            "properties": {
                "company_name": {"type": "string"},
                "founder_name": {"type": "string"},
                "known_facts": {"type": "array", "items": {"type": "string"}},
                "hypothesized_angles": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "angle_type": {"type": "string"},
                            "description": {"type": "string"},
                            "confidence": {"type": "string"},
                            "evidence": {"type": "string"},
                        },
                        "required": ["angle_type", "description", "confidence"],
                    },
                },
                "priority_questions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string"},
                            "target_signal": {"type": "string"},
                            "follow_up_if_vague": {"type": "string"},
                        },
                        "required": ["question", "target_signal"],
                    },
                },
                "interview_strategy": {"type": "string"},
                "avoid_topics": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["company_name", "founder_name", "known_facts",
                         "hypothesized_angles", "priority_questions",
                         "interview_strategy", "avoid_topics"],
        },
    }

    prompt = f"""Synthesize the following research into a briefing doc for the AI interviewer.
Apply the newsworthy angle framework from your instructions.

TRANSCRIPT FACTS:
{json.dumps(transcript_facts, indent=2)}

WEBSITE CONTENT:
{json.dumps(website_content, indent=2)}

LINKEDIN PROFILE:
{json.dumps(linkedin_profile, indent=2)}

Call return_briefing_doc with your findings."""

    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=system,
        tools=[output_tool],
        tool_choice={"type": "tool", "name": "return_briefing_doc"},
        messages=[{"role": "user", "content": prompt}],
    )

    # tool_use block contains the structured output directly as a dict
    for block in resp.content:
        if block.type == "tool_use" and block.name == "return_briefing_doc":
            logger.info("Briefing doc generated for: %s", block.input.get("company_name"))
            return block.input

    logger.warning("return_briefing_doc tool was not called")
    return {
        "company_name": "", "founder_name": "",
        "known_facts": [], "hypothesized_angles": [],
        "priority_questions": [], "interview_strategy": "",
        "avoid_topics": [],
    }


async def _direct_synthesis(client, system, tf, wc, lp) -> dict:
    return _build_briefing_from_dicts(tf, wc, lp)


def _extract_json(text: str) -> dict:
    """
    Robustly extract a JSON object from a Claude response that may contain
    markdown fences, preamble text, or trailing commentary.
    """
    # Try direct parse first
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # Strip ```json ... ``` or ``` ... ``` fences
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass

    # Find the first { ... } block in the response
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"No valid JSON found in response: {text[:200]}")


def _load_prompt() -> str:
    path = RESEARCH_PROMPT_PATH
    try:
        return open(path).read()
    except FileNotFoundError:
        return "You are a research agent for PressClub, a PR automation service."

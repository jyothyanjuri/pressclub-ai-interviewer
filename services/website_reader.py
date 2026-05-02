"""
Website Reader Service

Fetches a company website URL and uses Claude to extract structured content
relevant to newsworthy signal detection.
"""

import logging
import os
import time
from typing import Optional

import httpx
import anthropic

logger = logging.getLogger(__name__)

EXTRACT_FIELDS = [
    "product_description",
    "metrics_mentioned",
    "funding_mentioned",
    "customer_names",
    "world_first_claims",
    "world_best_claims",
    "benchmark_improvements",
]


async def read_website(url: str) -> dict:
    """
    Fetch URL content, pass to Claude for structured extraction.
    Runtime target: <15s.
    """
    start = time.monotonic()

    raw_html = await _fetch_url(url)
    if not raw_html:
        logger.warning("Could not fetch %s", url)
        return _empty_content(url)

    # Truncate to avoid token overflow — take first 12k chars (roughly the visible content)
    content_chunk = raw_html[:12000]

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Extract structured information from this company website content.\n"
                    f"URL: {url}\n\n"
                    f"Return a JSON object with these exact keys:\n"
                    f"- product_description: brief description of what the company does\n"
                    f"- metrics_mentioned: list of any numbers/stats cited (e.g. '10x faster', '99% accuracy')\n"
                    f"- funding_mentioned: any funding amounts or rounds mentioned (null if none)\n"
                    f"- customer_names: list of named customers or logos mentioned\n"
                    f"- world_first_claims: list of 'first ever' or unique positioning claims\n"
                    f"- world_best_claims: list of 'best in class' or benchmark claims\n"
                    f"- benchmark_improvements: list of performance/cost improvement stats\n\n"
                    f"ONLY include what is explicitly stated. Return null for missing fields.\n\n"
                    f"WEBSITE CONTENT:\n{content_chunk}"
                ),
            }
        ],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    import json
    try:
        result = json.loads(raw)
    except Exception:
        logger.warning("Failed to parse website extraction JSON")
        result = {"product_description": raw}

    result["source_url"] = url
    elapsed = time.monotonic() - start
    logger.info("Website reader for %s completed in %.1fs", url, elapsed)
    return result


async def _fetch_url(url: str) -> Optional[str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; PressClubBot/1.0; +https://pressclub.ai)"
        )
    }
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            # Return text content — strip excessive whitespace
            text = resp.text
            # Basic HTML tag removal for readability
            import re
            text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL)
            text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text)
            return text.strip()
    except Exception as exc:
        logger.error("Failed to fetch %s: %s", url, exc)
        return None


def _empty_content(url: str) -> dict:
    return {
        "source_url": url,
        "product_description": None,
        "metrics_mentioned": [],
        "funding_mentioned": None,
        "customer_names": [],
        "world_first_claims": [],
        "world_best_claims": [],
        "benchmark_improvements": [],
    }

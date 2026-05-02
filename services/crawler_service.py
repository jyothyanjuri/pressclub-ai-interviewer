"""
Crawler Service — Oxylabs LinkedIn Scraper

Wraps the Oxylabs Scraper API to extract founder/company profile data from LinkedIn.
"""

import asyncio
import logging
import os
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

OXYLABS_API_URL = "https://realtime.oxylabs.io/v1/queries"

REQUIRED_FIELDS = ["name", "current_role", "company_name", "work_history"]


async def scrape_linkedin_profile(linkedin_url: str) -> dict:
    """
    Scrape a LinkedIn profile via Oxylabs and return a normalized dict.
    Runtime target: <10s.
    """
    username = os.environ.get("OXYLABS_USERNAME")
    password = os.environ.get("OXYLABS_PASSWORD")

    if not username or not password:
        logger.warning("Oxylabs credentials not set — returning empty profile")
        return _empty_profile(linkedin_url)

    payload = {
        "source": "universal",
        "url": linkedin_url,
        "render": "html",
        "parse": True,
    }

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                OXYLABS_API_URL,
                json=payload,
                auth=(username, password),
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        logger.error("Oxylabs HTTP error %s: %s", exc.response.status_code, exc.response.text)
        return _empty_profile(linkedin_url)
    except Exception as exc:
        logger.error("Oxylabs request failed: %s", exc)
        return _empty_profile(linkedin_url)

    elapsed = time.monotonic() - start
    logger.info("Oxylabs response in %.1fs", elapsed)

    return _normalize_profile(data, linkedin_url)


def _normalize_profile(raw: dict, url: str) -> dict:
    """
    Parse Oxylabs response into a normalized profile dict.
    Oxylabs returns results under raw['results'][0]['content'].
    """
    try:
        content = raw["results"][0]["content"]
    except (KeyError, IndexError, TypeError):
        content = raw

    # Oxylabs parsed LinkedIn fields vary — handle both parsed and raw HTML fallback
    profile = {
        "source_url": url,
        "name": _extract(content, ["name", "full_name", "firstName"]),
        "current_role": _extract(content, ["headline", "title", "current_position"]),
        "company_name": _extract(content, ["company", "organization", "employer"]),
        "company_stage": _extract(content, ["company_size", "stage", "funding_stage"]),
        "work_history": _extract_list(content, ["experience", "work_history", "positions"]),
        "education": _extract_list(content, ["education", "schools"]),
        "summary": _extract(content, ["summary", "about", "bio"]),
        "location": _extract(content, ["location", "geo"]),
    }

    missing = [f for f in REQUIRED_FIELDS if not profile.get(f)]
    if missing:
        logger.warning("LinkedIn profile missing fields: %s", missing)

    return profile


def _extract(data: dict, keys: list) -> Optional[str]:
    for k in keys:
        val = data.get(k)
        if val and isinstance(val, str):
            return val.strip()
        if val and isinstance(val, dict):
            # Sometimes nested: {"title": "CEO"}
            for sub in ["title", "name", "text", "value"]:
                if val.get(sub):
                    return str(val[sub]).strip()
    return None


def _extract_list(data: dict, keys: list) -> list:
    for k in keys:
        val = data.get(k)
        if val and isinstance(val, list):
            return val
    return []


def _empty_profile(url: str) -> dict:
    return {
        "source_url": url,
        "name": None,
        "current_role": None,
        "company_name": None,
        "company_stage": None,
        "work_history": [],
        "education": [],
        "summary": None,
        "location": None,
    }

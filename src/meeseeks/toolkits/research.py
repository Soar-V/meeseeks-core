from __future__ import annotations

import collections
import os
import threading
import time
from urllib.parse import urlparse

import httpx

from meeseeks.toolkits import register_toolkit


class ToolUnavailableError(Exception):
    pass


class RateLimitError(Exception):
    pass


_firecrawl_sem = threading.Semaphore(10)
_domain_call_times: dict[str, list[float]] = collections.defaultdict(list)
_domain_lock = threading.Lock()


def firecrawl_scrape(url: str, options: dict | None = None) -> dict:
    """Scrape a URL via Firecrawl API, returning markdown content."""
    api_key = os.environ.get("FIRECRAWL_API_KEY")
    if not api_key:
        raise ToolUnavailableError("FIRECRAWL_API_KEY not set in environment")

    body: dict = {"url": url, "formats": ["markdown"]}
    if options:
        body.update(options)

    with _firecrawl_sem:
        resp = httpx.post(
            "https://api.firecrawl.dev/v1/scrape",
            headers={"Authorization": f"Bearer {api_key}"},
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

    payload = data.get("data") or {}
    return {
        "markdown": payload.get("markdown", ""),
        "credits_used": (payload.get("metadata") or {}).get("creditsUsed", 0),
        "url": url,
    }


def _domain_of(url: str) -> str:
    return urlparse(url).netloc


def http_fetch(url: str, timeout: int = 10) -> dict:
    """Fetch a URL via HTTP with per-domain rate limiting (60/min)."""
    domain = _domain_of(url)
    now = time.time()
    with _domain_lock:
        times = _domain_call_times[domain]
        times[:] = [t for t in times if now - t < 60]
        if len(times) >= 60:
            raise RateLimitError(f"Rate limit exceeded for {domain}: 60 requests/min")
        times.append(now)

    resp = httpx.get(url, timeout=timeout)
    return {
        "text": resp.text,
        "status_code": resp.status_code,
        "url": url,
    }


@register_toolkit
class ResearchToolkit:
    name = "research"
    tools = [firecrawl_scrape, http_fetch]
    requires_keys = ["FIRECRAWL_API_KEY"]

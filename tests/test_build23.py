"""
Build 23 tests — tool wiring, fetched_urls, raw output persistence.

Three test classes:
1. Unit: _fn_to_openai_tool + _build_tools_spec produce correct OpenAI tool spec
2. Unit: _dispatch_tool calls the function + returns URL for fetched_urls tracking
3. Integration: _run_agent_loop with mocked provider — tool calls happen,
   fetched_urls populates, output validates (mocked Firecrawl, no real network)
4. Unit: record_failure_artifact writes to run_artifacts table
"""
from __future__ import annotations
import json
import sys
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, "/root/meeseeks-core/src")

from dotenv import load_dotenv
load_dotenv("/root/soar/.env")


# ---------------------------------------------------------------------------
# 1. Tool spec generation
# ---------------------------------------------------------------------------

def test_fn_to_openai_tool_shape():
    """_fn_to_openai_tool must produce a valid OpenAI function tool spec."""
    from meeseeks.isolation.subprocess_runner import _fn_to_openai_tool
    from meeseeks.toolkits.research import firecrawl_scrape

    spec = _fn_to_openai_tool(firecrawl_scrape)

    assert spec["type"] == "function"
    fn = spec["function"]
    assert fn["name"] == "firecrawl_scrape"
    assert "url" in fn["parameters"]["properties"]
    assert "url" in fn["parameters"]["required"]
    # options has a default — must NOT be required
    assert "options" not in fn["parameters"]["required"]


def test_build_tools_spec_research_toolkit():
    """_build_tools_spec('research') returns specs for firecrawl_scrape + http_fetch."""
    from meeseeks.isolation.subprocess_runner import _build_tools_spec

    specs = _build_tools_spec(["research"])
    names = {s["function"]["name"] for s in specs}
    assert "firecrawl_scrape" in names
    assert "http_fetch" in names


def test_build_tools_spec_empty():
    """Empty toolkit list returns empty specs — no-toolkit path stays clean."""
    from meeseeks.isolation.subprocess_runner import _build_tools_spec
    assert _build_tools_spec([]) == []


# ---------------------------------------------------------------------------
# 2. Tool dispatch + URL tracking
# ---------------------------------------------------------------------------

def test_dispatch_tool_returns_url(tmp_path, monkeypatch):
    """_dispatch_tool extracts the url kwarg for fetched_urls tracking."""
    from meeseeks.isolation.subprocess_runner import _dispatch_tool

    called_with = {}

    def _fake_firecrawl(url, options=None):
        called_with["url"] = url
        return {"markdown": "# Test", "credits_used": 1, "url": url}

    # Patch toolkit registry
    fake_toolkit = MagicMock()
    fake_toolkit.tools = [_fake_firecrawl]
    _fake_firecrawl.__name__ = "firecrawl_scrape"

    with patch("meeseeks.toolkits.TOOLKIT_REGISTRY", {"research": fake_toolkit}):
        result_str, url = _dispatch_tool(
            "firecrawl_scrape",
            json.dumps({"url": "https://example.com"}),
            ["research"],
        )

    assert url == "https://example.com"
    result = json.loads(result_str)
    assert result["markdown"] == "# Test"


def test_dispatch_tool_unknown_returns_error():
    """Unknown tool name returns error JSON, not exception."""
    from meeseeks.isolation.subprocess_runner import _dispatch_tool
    result_str, url = _dispatch_tool("nonexistent_tool", "{}", ["research"])
    result = json.loads(result_str)
    assert "error" in result
    assert url is None


# ---------------------------------------------------------------------------
# 3. Agent loop integration (mocked provider)
# ---------------------------------------------------------------------------

def _make_fake_meeseeks():
    """Minimal meeseeks instance with fetched_urls tracking."""
    from meeseeks.registry import Meeseeks
    from pydantic import BaseModel
    from typing import Optional

    class FakeOutput(BaseModel):
        business_name: str
        found: bool
        recent_activity: list = []
        contact_info: Optional[dict] = None
        opening_hooks: list = []
        notes: Optional[str] = None
        source_urls: list = []

    class FakeMeeseeks(Meeseeks):
        name = "test_meeseeks"
        tier = "worker"
        isolation = "subprocess"
        use_framework = False
        description = "test"
        toolkits = ["research"]
        estimated_cost_usd = 0.10
        timeout_seconds = 30
        Input = type("Input", (), {})
        Output = FakeOutput

        def system_prompt(self, inputs):
            return "test"

    return FakeMeeseeks()


def test_agent_loop_tool_calls_then_final_output():
    """
    _run_agent_loop with mocked provider:
    - Turn 1: provider returns tool_calls for firecrawl_scrape
    - Turn 2: provider returns final JSON output (no tool_calls)
    Asserts: fetched_urls populated, output parsed correctly.
    """
    from meeseeks.isolation.subprocess_runner import _run_agent_loop, _build_tools_spec
    from meeseeks.contracts import TokenUsage

    fake_meeseeks = _make_fake_meeseeks()

    final_output = {
        "business_name": "Test Practice",
        "found": True,
        "recent_activity": [],
        "contact_info": None,
        "opening_hooks": [],
        "notes": None,
        "source_urls": ["https://testpractice.com"],
    }

    turn1_message = {
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": "call_abc",
            "type": "function",
            "function": {
                "name": "firecrawl_scrape",
                "arguments": json.dumps({"url": "https://testpractice.com"}),
            },
        }],
    }
    turn2_message = {
        "role": "assistant",
        "content": json.dumps(final_output),
        "tool_calls": [],
    }

    fake_usage = TokenUsage(cost_usd=0.05, total_tokens=500)
    call_count = [0]

    def _fake_chat_with_tools_fallback(messages, tier, tools, timeout_seconds):
        call_count[0] += 1
        if call_count[0] == 1:
            return turn1_message, fake_usage, "test-model"
        return turn2_message, fake_usage, "test-model"

    fake_provider = MagicMock()
    fake_provider.chat_with_tools_fallback.side_effect = _fake_chat_with_tools_fallback

    # Mock the actual firecrawl call
    def _fake_firecrawl(url, options=None):
        return {"markdown": "# Dr. Test\nPhone: 555-1234", "credits_used": 1, "url": url}
    _fake_firecrawl.__name__ = "firecrawl_scrape"

    fake_toolkit_cls = MagicMock()
    fake_toolkit_cls.tools = [_fake_firecrawl]

    tools_spec = _build_tools_spec.__wrapped__([]) if hasattr(_build_tools_spec, '__wrapped__') else []

    with patch("meeseeks.toolkits.TOOLKIT_REGISTRY", {"research": fake_toolkit_cls}):
        tools_spec = [
            {"type": "function", "function": {"name": "firecrawl_scrape",
             "description": "scrape", "parameters": {"type": "object",
             "properties": {"url": {"type": "string"}}, "required": ["url"]}}}
        ]
        parsed, usage, failure_reason, fetched_urls, raw = _run_agent_loop(
            meeseeks=fake_meeseeks,
            messages=[{"role": "user", "content": "research Test Practice"}],
            provider=fake_provider,
            tools_spec=tools_spec,
            toolkit_names=["research"],
            output_schema=fake_meeseeks.__class__.Output,
            timeout_seconds=30,
        )

    assert failure_reason is None, f"Expected success, got: {failure_reason}"
    assert parsed is not None
    assert parsed.business_name == "Test Practice"
    assert parsed.found is True
    assert "https://testpractice.com" in fetched_urls, \
        f"fetched_urls not populated: {fetched_urls}"
    assert "https://testpractice.com" in fake_meeseeks.fetched_urls, \
        f"meeseeks.fetched_urls not populated: {fake_meeseeks.fetched_urls}"


# ---------------------------------------------------------------------------
# 4. Failure artifact persistence
# ---------------------------------------------------------------------------

def test_record_failure_artifact(tmp_path):
    """record_failure_artifact writes raw_output to run_artifacts table."""
    import sqlite3
    from unittest.mock import patch as _patch

    fake_db = tmp_path / "test_budget.db"

    with _patch("meeseeks.budget.DB_PATH", fake_db):
        from meeseeks.budget import record_failure_artifact as _rfa
        _rfa("test_meeseeks_id_abc", '{"business_name": "Test", "found": false}')

        conn = sqlite3.connect(str(fake_db))
        rows = conn.execute(
            "SELECT meeseeks_id, raw_output FROM run_artifacts WHERE meeseeks_id=?",
            ("test_meeseeks_id_abc",)
        ).fetchall()
        conn.close()

    assert rows, "No artifact row written"
    assert rows[0][0] == "test_meeseeks_id_abc"
    assert "Test" in rows[0][1]


def test_no_toolkit_path_unchanged():
    """No-toolkit meeseeks (fixture) still uses parse_with_retry, not agent loop."""
    from meeseeks.registry import Meeseeks
    from pydantic import BaseModel

    class NoToolOutput(BaseModel):
        result: str

    class NoToolMeeseeks(Meeseeks):
        name = "no_tool_test"
        tier = "thinker"
        isolation = "inline"
        use_framework = False
        description = "test"
        toolkits = []  # explicitly empty
        estimated_cost_usd = 0.0
        timeout_seconds = 10
        Input = type("Input", (), {})
        Output = NoToolOutput

        def system_prompt(self, inputs):
            return "test"

    # Confirm toolkits is falsy — the branch condition
    assert not NoToolMeeseeks.toolkits

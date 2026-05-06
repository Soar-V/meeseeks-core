from __future__ import annotations

import os
from unittest import mock

import pytest


def test_firecrawl_no_api_key_raises():
    from meeseeks.toolkits.research import ToolUnavailableError, firecrawl_scrape

    env = {k: v for k, v in os.environ.items() if k != "FIRECRAWL_API_KEY"}
    with mock.patch.dict(os.environ, env, clear=True):
        with pytest.raises(ToolUnavailableError):
            firecrawl_scrape("https://example.com")


def test_http_fetch_returns_correct_keys():
    from meeseeks.toolkits.research import http_fetch

    mock_response = mock.MagicMock()
    mock_response.text = '{"args": {}}'
    mock_response.status_code = 200

    with mock.patch("meeseeks.toolkits.research.httpx.get", return_value=mock_response):
        result = http_fetch("https://httpbin.org/get")

    assert "text" in result
    assert "status_code" in result
    assert "url" in result
    assert result["status_code"] == 200
    assert result["url"] == "https://httpbin.org/get"


def test_research_toolkit_in_registry():
    import meeseeks.toolkits.research  # noqa: F401 — triggers @register_toolkit

    from meeseeks.toolkits import TOOLKIT_REGISTRY

    assert "research" in TOOLKIT_REGISTRY
    assert TOOLKIT_REGISTRY["research"].name == "research"

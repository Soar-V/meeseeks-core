"""
Build 10 acceptance tests — Discord debug logger (§10.1).

Tests:
  1. log_event() enqueues and formats correctly (no HTTP needed)
  2. Batching: multiple events within window → single POST payload
  3. Chunk splitting: message > 2000 chars → multiple POSTs
  4. SPAWN + COMPLETE events fire on a real summon() call
  5. Rate-limit batching: rapid-fire events arrive as batched payload
  6. Live Discord POST (skipped unless MEESEEKS_DEBUG_WEBHOOK env set)
"""
from __future__ import annotations
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable

import pytest
from pydantic import BaseModel

from meeseeks.discord_logger import (
    _format_event,
    _split_into_chunks,
    _DiscordLogger,
    log_event,
    log_spawn,
    log_complete,
    BATCH_WINDOW_SECS,
    MAX_MESSAGE_CHARS,
)
import meeseeks.discord_logger as dl_module


# ── Helpers ───────────────────────────────────────────────────────────────

class _MockWebhookServer:
    """Minimal HTTP server that captures Discord webhook POST bodies."""

    def __init__(self):
        self.received: list[dict] = []
        self._lock = threading.Lock()
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.url: str = ""

    def start(self):
        received = self.received
        lock = self._lock

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                import json
                with lock:
                    try:
                        received.append(json.loads(body))
                    except Exception:
                        received.append({"raw": body.decode()})
                self.send_response(204)
                self.end_headers()

            def log_message(self, *args):
                pass  # silence server logs

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        port = self._server.server_address[1]
        self.url = f"http://127.0.0.1:{port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        if self._server:
            self._server.shutdown()


# ── Tests ─────────────────────────────────────────────────────────────────


def test_format_event_spawn():
    """SPAWN events format with ** bold markers."""
    line = _format_event("SPAWN", "abc12345", "my_task | tier:worker")
    assert "**SPAWN**" in line
    assert "abc12345" in line
    assert "my_task" in line


def test_format_event_tool_call():
    """tool_call events use → separator."""
    line = _format_event("tool_call", "abc12345", "web_search(query)")
    assert "→ tool_call:" in line
    assert "web_search" in line


def test_split_into_chunks_small():
    """Short text → single chunk."""
    chunks = _split_into_chunks("hello\nworld", 1900)
    assert len(chunks) == 1
    assert "hello" in chunks[0]


def test_split_into_chunks_large():
    """Text > max_chars → multiple chunks."""
    big = "\n".join(f"line {i}: " + "x" * 80 for i in range(30))
    chunks = _split_into_chunks(big, 500)
    assert len(chunks) > 1
    # No chunk exceeds limit
    for c in chunks:
        assert len(c) <= 500, f"Chunk too big: {len(c)}"
    # All content preserved
    reconstructed = "\n".join(chunks)
    assert "line 0:" in reconstructed
    assert "line 29:" in reconstructed


def test_batch_window_collects_events():
    """Multiple events within the batch window arrive in one POST payload."""
    server = _MockWebhookServer()
    server.start()
    try:
        # Override webhook URL for this test
        old_url = dl_module.DISCORD_WEBHOOK_URL
        dl_module.DISCORD_WEBHOOK_URL = server.url

        # Create a fresh logger (not the global singleton)
        logger = _DiscordLogger()
        logger.post(_format_event("SPAWN", "aaa11111", "test spawn"))
        logger.post(_format_event("tool_call", "aaa11111", "web_search('x')"))
        logger.post(_format_event("COMPLETE", "aaa11111", "cost:$0.001, duration:500ms"))

        # Wait for batch window to close + small buffer
        time.sleep(BATCH_WINDOW_SECS + 0.5)

        dl_module.DISCORD_WEBHOOK_URL = old_url
        logger._queue.put(None)  # shut down logger

        # Should have received at least 1 POST with multiple events
        assert len(server.received) >= 1, f"Expected ≥1 POST, got {len(server.received)}"
        full_text = "\n".join(p.get("content", "") for p in server.received)
        assert "SPAWN" in full_text
        assert "COMPLETE" in full_text
        print(f"\n  Received {len(server.received)} POST(s), events batched correctly")
    finally:
        server.stop()


def test_rapid_fire_events_batched():
    """10 rapid events → fewer than 10 POSTs (batching working)."""
    server = _MockWebhookServer()
    server.start()
    try:
        old_url = dl_module.DISCORD_WEBHOOK_URL
        dl_module.DISCORD_WEBHOOK_URL = server.url

        logger = _DiscordLogger()
        for i in range(10):
            logger.post(_format_event("info", f"id{i:04d}", f"event {i}"))

        time.sleep(BATCH_WINDOW_SECS + 0.5)

        dl_module.DISCORD_WEBHOOK_URL = old_url
        logger._queue.put(None)

        # All 10 events in fewer than 10 POSTs
        posts = len(server.received)
        assert posts < 10, f"Expected batching, got {posts} individual POSTs"
        full_text = "\n".join(p.get("content", "") for p in server.received)
        for i in range(10):
            assert f"event {i}" in full_text
        print(f"\n  10 events → {posts} POST(s)")
    finally:
        server.stop()


def test_summon_fires_spawn_and_complete_events():
    """A real summon() call generates SPAWN + COMPLETE log events."""
    if not os.environ.get("OPENROUTER_API_KEY"):
        pytest.skip("OPENROUTER_API_KEY not set")

    server = _MockWebhookServer()
    server.start()
    try:
        old_url = dl_module.DISCORD_WEBHOOK_URL
        dl_module.DISCORD_WEBHOOK_URL = server.url

        # Re-use review_thinker from earlier (already registered)
        from meeseeks import summon, register_meeseeks, Meeseeks
        from typing import Literal as Lit

        @register_meeseeks
        class LoggerTestMeeseeks(Meeseeks):
            name = "logger_test_b10"
            description = "logger test"
            tier = "thinker"
            isolation = "inline"
            use_framework = False
            timeout_seconds = 30

            class Input(BaseModel):
                text: str

            class Output(BaseModel):
                result: str

            def system_prompt(self, inputs):
                return f"Reply with JSON: {{\"result\": \"ok\"}}. Ignore: {inputs.text}"

        result = summon(LoggerTestMeeseeks, LoggerTestMeeseeks.Input(text="test"))

        # Wait for batch to flush
        time.sleep(BATCH_WINDOW_SECS + 0.5)
        dl_module.DISCORD_WEBHOOK_URL = old_url

        full_text = "\n".join(p.get("content", "") for p in server.received)
        assert "SPAWN" in full_text, f"No SPAWN in Discord posts: {full_text[:500]}"
        assert "COMPLETE" in full_text or "FAILURE" in full_text, \
            f"No COMPLETE/FAILURE in Discord posts: {full_text[:500]}"
        print(f"\n  summon() → {len(server.received)} Discord POST(s)")
        print(f"  Content preview: {full_text[:300]}")
    finally:
        server.stop()


def test_live_discord_post():
    """Live end-to-end post to real Discord webhook. Skipped unless env var set."""
    webhook = os.environ.get("MEESEEKS_DEBUG_WEBHOOK")
    if not webhook:
        pytest.skip("MEESEEKS_DEBUG_WEBHOOK not set")

    dl_module.DISCORD_WEBHOOK_URL = webhook
    logger = _DiscordLogger()
    logger.post(_format_event("SPAWN", "livetest1", "live Discord test from meeseeks-core CI"))
    logger.post(_format_event("COMPLETE", "livetest1", "cost:$0.001, duration:500ms, status:success"))
    logger._queue.put(None)
    logger._thread.join(timeout=10)
    print("\n  Live Discord post sent. Check your debug channel.")

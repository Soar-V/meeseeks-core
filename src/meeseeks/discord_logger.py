"""
§10.1 Discord debug logger — firehose for the debug channel.

Architecture:
- Single background thread drains a log queue and posts to Discord
- Batches events within 2s windows to stay under Discord's 5 msg/sec rate limit
- Each batch is one Discord message (up to 2000 chars; overflow splits)
- Caller posts fire-and-forget via log_event() — never blocks
- Auto-flushes remaining events on process exit via atexit

Event format (plain text, timestamped):
  [HH:MM:SS] SPAWN research_prospect#a3f2
             input: {prospect_name: "Anigian"}
             model: claude-haiku, est_cost: $0.08

  [HH:MM:SS] research_prospect#a3f2 → COMPLETE
             cost: $0.09, duration: 61s, status: success
"""
from __future__ import annotations
import atexit
import os
import queue
import threading
import time
from datetime import datetime, timezone
from typing import Literal

import httpx

# ── Config ────────────────────────────────────────────────────────────────

DISCORD_WEBHOOK_URL: str | None = None  # set via init() or MEESEEKS_DEBUG_WEBHOOK env
BATCH_WINDOW_SECS: float = 2.0          # collect events for this long before posting
MAX_MESSAGE_CHARS: int = 1900           # Discord limit is 2000; leave buffer


# ── Event types ───────────────────────────────────────────────────────────

EventKind = Literal["SPAWN", "tool_call", "tool_result", "COMPLETE", "FAILURE", "TIMEOUT", "info"]


def _ts() -> str:
    return datetime.now(tz=timezone.utc).strftime("%H:%M:%S")


def _format_event(kind: EventKind, meeseeks_id: str, detail: str) -> str:
    """Format one log line."""
    if kind in ("SPAWN", "COMPLETE", "FAILURE", "TIMEOUT"):
        # Bold section headers
        return f"[{_ts()}] **{kind}** {meeseeks_id}\n           {detail}"
    return f"[{_ts()}] {meeseeks_id} → {kind}: {detail}"


# ── Background logger ─────────────────────────────────────────────────────

class _DiscordLogger:
    def __init__(self):
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._thread = threading.Thread(target=self._drain, daemon=True, name="meeseeks-discord-logger")
        self._thread.start()
        atexit.register(self._flush_on_exit)

    def post(self, line: str) -> None:
        """Fire-and-forget: enqueue a formatted log line."""
        self._queue.put_nowait(line)

    def _drain(self) -> None:
        """Background thread: batch events and POST to Discord webhook."""
        while True:
            batch: list[str] = []
            deadline = time.monotonic() + BATCH_WINDOW_SECS

            # Collect until batch window closes or sentinel received
            while time.monotonic() < deadline:
                try:
                    item = self._queue.get(timeout=max(0.01, deadline - time.monotonic()))
                except queue.Empty:
                    break
                if item is None:
                    # Sentinel — drain remaining and exit
                    self._post_batch(batch)
                    return
                batch.append(item)

            if batch:
                self._post_batch(batch)

    def _post_batch(self, lines: list[str]) -> None:
        """Send one or more Discord messages from batched lines."""
        if not lines:
            return
        url = DISCORD_WEBHOOK_URL or os.environ.get("MEESEEKS_DEBUG_WEBHOOK")
        if not url:
            return  # no webhook configured — silent drop

        # Split into ≤MAX_MESSAGE_CHARS chunks
        chunks = _split_into_chunks("\n".join(lines), MAX_MESSAGE_CHARS)
        for chunk in chunks:
            try:
                with httpx.Client(timeout=5) as client:
                    resp = client.post(url, json={"content": f"```\n{chunk}\n```"})
                    resp.raise_for_status()
            except Exception:
                pass  # debug logger must never crash the parent

    def _flush_on_exit(self) -> None:
        """Drain remaining events on process exit."""
        self._queue.put(None)  # sentinel
        self._thread.join(timeout=5)


def _split_into_chunks(text: str, max_chars: int) -> list[str]:
    """Split text into chunks of at most max_chars characters at line boundaries."""
    lines = text.splitlines()
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        if current_len + len(line) + 1 > max_chars and current:
            chunks.append("\n".join(current))
            current = [line]
            current_len = len(line)
        else:
            current.append(line)
            current_len += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


_logger: _DiscordLogger | None = None
_lock = threading.Lock()


def _get_logger() -> _DiscordLogger:
    global _logger
    if _logger is None:
        with _lock:
            if _logger is None:
                _logger = _DiscordLogger()
    return _logger


# ── Public API ────────────────────────────────────────────────────────────

def init(webhook_url: str) -> None:
    """Configure the webhook URL. Call once at startup."""
    global DISCORD_WEBHOOK_URL
    DISCORD_WEBHOOK_URL = webhook_url
    _get_logger()  # start background thread now


def log_event(
    kind: EventKind,
    meeseeks_id: str,
    detail: str,
) -> None:
    """
    Post one debug event. Non-blocking — enqueues and returns immediately.

    Usage::
        from meeseeks.discord_logger import log_event
        log_event("SPAWN", result.meeseeks_id, f"input: {inputs!r}, tier: {tier}")
        log_event("COMPLETE", result.meeseeks_id, f"cost: ${cost:.4f}, duration: {ms}ms")
    """
    line = _format_event(kind, meeseeks_id, detail)
    _get_logger().post(line)


def log_spawn(meeseeks_id: str, name: str, tier: str, est_cost: float, inputs_repr: str) -> None:
    """Convenience: log a SPAWN event."""
    log_event("SPAWN", meeseeks_id, f"{name} | tier:{tier} | est:${est_cost:.3f} | {inputs_repr[:120]}")


def log_complete(meeseeks_id: str, status: str, cost_usd: float, duration_ms: int) -> None:
    """Convenience: log a COMPLETE/FAILURE/TIMEOUT event."""
    kind: EventKind = "COMPLETE" if status == "success" else ("TIMEOUT" if status == "timeout" else "FAILURE")
    log_event(kind, meeseeks_id, f"cost:${cost_usd:.5f}, duration:{duration_ms}ms, status:{status}")

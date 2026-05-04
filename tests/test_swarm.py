"""
Swarm acceptance test — Builds 8 + 9 + 10 combined under contention.

Spec:
  - 8 workers in parallel, WORKER_SEM cap is 5 → 3 must queue
  - One worker intentionally times out (timeout_seconds=3, worker sleeps 30)
  - One worker intentionally crashes (os._exit(1))
  - Remaining 6 should succeed
  - Discord debug channel: SPAWN + COMPLETE/FAILURE/TIMEOUT for all 8, correct IDs, no drops
  - Budget: 8 rows after completion
  - ps aux: zero zombies
  - Semaphore: 5 free slots after all complete

Module-level meeseeks classes required for pickle (spawn mode).
"""
from __future__ import annotations
import os
import sqlite3
import subprocess as sp
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel

from meeseeks import register_meeseeks, Meeseeks, summon, MeeseeksResult
import meeseeks.discord_logger as dl_module

# ── Require API key ───────────────────────────────────────────────────────
pytestmark = pytest.mark.skipif(
    not os.environ.get("OPENROUTER_API_KEY"),
    reason="OPENROUTER_API_KEY not set",
)


# ── Mock webhook server ───────────────────────────────────────────────────

class MockWebhook:
    def __init__(self):
        self.posts: list[str] = []
        self._lock = threading.Lock()

    def start(self) -> str:
        posts = self.posts
        lock = self._lock

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                import json
                n = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(n)
                with lock:
                    try:
                        posts.append(json.loads(body).get("content", ""))
                    except Exception:
                        posts.append(body.decode())
                self.send_response(204)
                self.end_headers()

            def log_message(self, *args):
                pass

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return f"http://127.0.0.1:{port}"

    def stop(self):
        self._server.shutdown()

    def all_text(self) -> str:
        return "\n".join(self.posts)


# ── Module-level meeseeks (must be importable for pickle) ─────────────────

@register_meeseeks
class SwarmWorker(Meeseeks):
    """Normal worker — should succeed."""
    name = "swarm_worker"
    description = "Swarm test worker"
    tier = "thinker"
    isolation = "subprocess"
    use_framework = False
    timeout_seconds = 90

    class Input(BaseModel):
        text: str
        index: int

    class Output(BaseModel):
        sentiment: Literal["positive", "negative", "neutral"]
        index: int

    def system_prompt(self, inputs):
        return (
            f"Classify sentiment of '{inputs.text}'. "
            f"Return JSON: {{\"sentiment\": \"positive\"|\"negative\"|\"neutral\", \"index\": {inputs.index}}}. "
            "JSON only."
        )

    def format(self, output):
        return f"[{output.index}] {output.sentiment}"


@register_meeseeks
class SwarmTimeouter(Meeseeks):
    """Worker that always times out — timeout_seconds=3."""
    name = "swarm_timeouter"
    description = "Swarm test — intentional timeout"
    tier = "thinker"
    isolation = "subprocess"
    use_framework = False
    timeout_seconds = 3  # very short — worker will sleep longer than this

    class Input(BaseModel):
        index: int

    class Output(BaseModel):
        done: bool

    def system_prompt(self, inputs):
        # The worker will time out before this completes — but we need a valid prompt
        # The actual timeout is enforced by the parent, not the LLM
        return "Sleep for 60 seconds then return JSON: {\"done\": true}"


@register_meeseeks
class SwarmCrasher(Meeseeks):
    """Worker that crashes via os._exit(1) inside the subprocess."""
    name = "swarm_crasher"
    description = "Swarm test — intentional crash"
    tier = "thinker"
    isolation = "subprocess"
    use_framework = False
    timeout_seconds = 30

    class Input(BaseModel):
        index: int

    class Output(BaseModel):
        done: bool

    def system_prompt(self, inputs):
        # Will never be called — __init__ override below crashes first
        return ""

    def __init__(self):
        super().__init__()
        # This runs inside the subprocess after spawn — crashes worker process cleanly
        import os as _os
        _os._exit(1)


# ── Swarm acceptance test ─────────────────────────────────────────────────

def test_swarm_8_workers():
    """
    Full integration: 8 workers above the SEM(5) cap.
    Assertions:
      A. All 8 return (no deadlock, no hang) — 6 success, 1 timeout, 1 crash
      B. Discord events: SPAWN + terminal event for all 8, IDs consistent
      C. Budget: 8 rows recorded
      D. Zero zombies after completion
    """
    webhook = MockWebhook()
    url = webhook.start()

    old_url = dl_module.DISCORD_WEBHOOK_URL
    dl_module.DISCORD_WEBHOOK_URL = url

    # Reset logger singleton so it picks up the new URL
    old_logger = dl_module._logger
    dl_module._logger = None

    try:
        _run_swarm_assertions(webhook)
    finally:
        # Flush logger, restore state
        if dl_module._logger:
            dl_module._logger._queue.put(None)
            dl_module._logger._thread.join(timeout=8)
        dl_module._logger = old_logger
        dl_module.DISCORD_WEBHOOK_URL = old_url
        webhook.stop()


def _run_swarm_assertions(webhook: MockWebhook):
    # Build 8 spawn tasks:
    #   indices 1-6: normal SwarmWorker (should succeed)
    #   index 7: SwarmTimeouter (should timeout)
    #   index 8: SwarmCrasher  (should crash → failure)

    TEXTS = [
        "This is absolutely amazing!",
        "I hate waiting in queues.",
        "The weather is fine today.",
        "Brilliant work on the framework!",
        "This is frustrating and slow.",
        "It works as expected.",
    ]

    def _spawn(task):
        kind, idx = task
        if kind == "normal":
            return summon(SwarmWorker, SwarmWorker.Input(text=TEXTS[idx % len(TEXTS)], index=idx))
        elif kind == "timeout":
            return summon(SwarmTimeouter, SwarmTimeouter.Input(index=idx))
        else:  # crash
            return summon(SwarmCrasher, SwarmCrasher.Input(index=idx))

    tasks = [("normal", i) for i in range(1, 7)] + [("timeout", 7), ("crash", 8)]

    t_start = time.monotonic()
    results: list[MeeseeksResult] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_spawn, t) for t in tasks]
        for f in as_completed(futures):
            results.append(f.result())
    elapsed = time.monotonic() - t_start

    # ── Assertion A: All 8 returned, correct statuses ─────────────────────
    assert len(results) == 8, f"Expected 8 results, got {len(results)}"

    statuses = [r.status for r in results]
    success_count = statuses.count("success")
    timeout_count = statuses.count("timeout")
    failure_count = statuses.count("failure")

    print(f"\n  Swarm completed in {elapsed:.1f}s")
    print(f"  Results: {success_count} success, {timeout_count} timeout, {failure_count} failure")
    for r in sorted(results, key=lambda x: x.meeseeks_id):
        print(f"    {r.meeseeks_id} | {r.status:8s} | ${r.cost.cost_usd:.5f} | {r.duration_ms}ms"
              + (f" | data.index={r.data.index}" if r.status == "success" and hasattr(r.data, "index") else "")
              + (f" | reason: {r.reason}" if r.status != "success" else ""))

    assert success_count == 6, f"Expected 6 success, got {success_count}. Statuses: {statuses}"
    assert timeout_count == 1, f"Expected 1 timeout, got {timeout_count}"
    assert failure_count == 1, f"Expected 1 failure, got {failure_count}"

    # ── Assertion B: Discord events ───────────────────────────────────────
    # Wait for batch window to flush
    time.sleep(dl_module.BATCH_WINDOW_SECS + 1.0)
    full_text = webhook.all_text()

    spawn_ids_in_results = {r.meeseeks_id for r in results}
    spawn_ids_in_discord = set()
    for line in full_text.splitlines():
        # Extract 8-char hex IDs from log lines
        import re
        matches = re.findall(r'\b([0-9a-f]{8})\b', line)
        spawn_ids_in_discord.update(matches)

    # All result IDs should appear in Discord output
    missing_from_discord = spawn_ids_in_results - spawn_ids_in_discord
    print(f"\n  Discord posts: {len(webhook.posts)} batches")
    print(f"  Spawn IDs in results: {spawn_ids_in_results}")
    print(f"  Spawn IDs found in Discord: {spawn_ids_in_discord & spawn_ids_in_results}")
    print(f"  Missing from Discord: {missing_from_discord}")
    print(f"  Discord text preview:\n{full_text[:1000]}")

    # SPAWN events for all 8
    spawn_event_count = full_text.count("**SPAWN**")
    terminal_event_count = (full_text.count("**COMPLETE**") +
                            full_text.count("**FAILURE**") +
                            full_text.count("**TIMEOUT**"))

    print(f"\n  SPAWN events in Discord: {spawn_event_count}")
    print(f"  Terminal events (COMPLETE/FAILURE/TIMEOUT): {terminal_event_count}")

    assert spawn_event_count == 8, f"Expected 8 SPAWN events, got {spawn_event_count}"
    assert terminal_event_count == 8, f"Expected 8 terminal events, got {terminal_event_count}"
    assert not missing_from_discord, f"IDs missing from Discord: {missing_from_discord}"

    # ── Assertion C: Budget rows ───────────────────────────────────────────
    from meeseeks.budget import cost_breakdown
    breakdown = cost_breakdown(days=1)

    swarm_spawns = (
        breakdown.get("swarm_worker", {}).get("spawns", 0) +
        breakdown.get("swarm_timeouter", {}).get("spawns", 0) +
        breakdown.get("swarm_crasher", {}).get("spawns", 0)
    )
    print(f"\n  Budget swarm rows: {swarm_spawns}")
    print(f"  Breakdown: {breakdown.get('swarm_worker')} | {breakdown.get('swarm_timeouter')} | {breakdown.get('swarm_crasher')}")
    assert swarm_spawns >= 8, f"Expected ≥8 budget rows, got {swarm_spawns}"

    # ── Assertion D: Zero zombies ──────────────────────────────────────────
    ps = sp.run(["ps", "aux"], capture_output=True, text=True)
    defunct = [l for l in ps.stdout.splitlines() if "<defunct>" in l]
    print(f"\n  Defunct processes: {len(defunct)}")
    assert len(defunct) == 0, f"Zombie processes found: {defunct}"

    # ── Bonus: Semaphore slots available ──────────────────────────────────
    # After all workers complete, all slots should be available again.
    # We verify by acquiring 5 times — if sem were leaked, this would block.
    from meeseeks.summon import _get_semaphore
    sem = _get_semaphore("worker")
    acquired = 0
    for _ in range(5):
        ok = sem.acquire(block=False)
        if ok:
            acquired += 1
    # Release all we acquired
    for _ in range(acquired):
        sem.release()

    print(f"\n  Semaphore: acquired {acquired}/5 slots non-blocking (expected 5)")
    assert acquired == 5, f"Expected 5 free semaphore slots, only got {acquired} — leak detected"

    print("\n  ✅ All 4 assertions passed.")

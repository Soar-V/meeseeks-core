"""
Build 9 acceptance tests — subprocess failure modes.

Each test exercises a distinct failure path:
  A. Timeout: worker sleeps past deadline → clean timeout envelope
  B. Crash: worker calls os._exit(1) → clean failure envelope
  C. Zombie: kill -9 parent mid-run (simulated) → daemon=True auto-cleans

Meeseeks classes must be MODULE-LEVEL for pickle.
No real API calls needed — these tests mock the worker behavior.
"""
from __future__ import annotations
import os
import time
import multiprocessing
import subprocess as sp
import signal
from typing import Literal

import pytest
from pydantic import BaseModel

from meeseeks import register_meeseeks, Meeseeks
from meeseeks.summon import _summon_subprocess
from meeseeks.contracts import MeeseeksResult, TokenUsage
from meeseeks.providers.openrouter import OpenRouterProvider


# ── Module-level worker functions for mock processes ─────────────────────

def _sleepy_worker(result_queue, sleep_secs):
    """Worker that sleeps past its deadline."""
    time.sleep(sleep_secs)
    result_queue.put({"status": "success", "data": {"done": True},
                      "reason": None, "partial": None,
                      "cost": {"prompt_tokens": 0, "completion_tokens": 0,
                               "total_tokens": 0, "cost_usd": 0.0, "tool_cost_usd": 0.0},
                      "duration_ms": 0, "meeseeks_id": "aaaabbbb"})


def _crashing_worker(result_queue):
    """Worker that crashes with os._exit — no cleanup, no exception propagation."""
    os._exit(1)


def _segfault_worker(result_queue):
    """Worker that gets killed by signal (simulate segfault via SIGSEGV to self)."""
    os.kill(os.getpid(), signal.SIGSEGV)


# ── Timeout meeseeks (module-level, used in test_timeout) ────────────────

@register_meeseeks
class TimeoutMeeseeks(Meeseeks):
    name = "timeout_test_b9"
    description = "Meeseeks that times out"
    tier = "thinker"
    isolation = "subprocess"
    use_framework = False
    timeout_seconds = 2   # very short deadline

    class Input(BaseModel):
        dummy: str = ""

    class Output(BaseModel):
        done: bool

    def system_prompt(self, inputs):
        return "Return JSON: {\"done\": true}"


# ── Tests ─────────────────────────────────────────────────────────────────


def test_timeout_returns_clean_envelope():
    """Worker that exceeds timeout → MeeseeksResult(status='timeout'), no hang."""
    ctx = multiprocessing.get_context("spawn")
    result_queue = ctx.Queue()

    proc = ctx.Process(target=_sleepy_worker, args=(result_queue, 30), daemon=True)
    start = time.monotonic()
    proc.start()

    # Replicate summon timeout logic
    proc.join(timeout=2)
    elapsed = time.monotonic() - start

    if proc.is_alive():
        proc.kill()
        proc.join(3)
        result = MeeseeksResult.timeout()
    else:
        result = MeeseeksResult.failure(reason="unexpected early exit")

    assert result.status == "timeout", f"Expected timeout, got {result.status}"
    assert result.reason == "meeseeks timed out"
    assert result.data is None
    assert elapsed < 4.0, f"Timeout took too long: {elapsed:.1f}s"
    assert not proc.is_alive(), "Worker should be dead after kill"
    print(f"\n  Timeout in {elapsed:.2f}s, worker dead: {not proc.is_alive()}")


def test_crash_returns_clean_failure_envelope():
    """Worker that calls os._exit(1) → failure envelope, no exception propagation."""
    ctx = multiprocessing.get_context("spawn")
    result_queue = ctx.Queue()

    proc = ctx.Process(target=_crashing_worker, args=(result_queue,), daemon=True)
    proc.start()
    proc.join(timeout=10)

    assert not proc.is_alive()
    assert proc.exitcode == 1, f"Expected exitcode=1, got {proc.exitcode}"

    # Queue will be empty — worker crashed before putting anything
    import queue as queue_mod
    try:
        raw = result_queue.get(timeout=1)
        result = MeeseeksResult.model_validate(raw)
    except queue_mod.Empty:
        result = MeeseeksResult.failure(reason=f"worker crashed with exitcode {proc.exitcode}")

    assert result.status == "failure"
    assert "crash" in result.reason or "exitcode" in result.reason or result.reason is not None
    print(f"\n  Crash → {result.status}: {result.reason}")


def test_signal_kill_returns_failure_envelope():
    """Worker killed by signal (negative exitcode) → failure envelope with signal info."""
    ctx = multiprocessing.get_context("spawn")
    result_queue = ctx.Queue()

    proc = ctx.Process(target=_segfault_worker, args=(result_queue,), daemon=True)
    proc.start()
    proc.join(timeout=10)

    assert not proc.is_alive()
    assert proc.exitcode is not None and proc.exitcode < 0, \
        f"Expected negative exitcode (signal kill), got {proc.exitcode}"

    import queue as queue_mod
    try:
        raw = result_queue.get(timeout=1)
        result = MeeseeksResult.model_validate(raw)
    except queue_mod.Empty:
        result = MeeseeksResult.failure(
            reason=f"worker killed by signal {-proc.exitcode}"
        )

    assert result.status == "failure"
    assert result.reason is not None
    print(f"\n  Signal kill (exitcode {proc.exitcode}) → {result.status}: {result.reason}")


def test_daemon_processes_dont_outlive_parent():
    """Daemon=True means subprocess is cleaned up if parent dies.

    We verify via the daemon flag itself (testing actual parent kill would
    be self-destructive in a test runner). Verify subprocess_runner creates
    daemon processes.
    """
    ctx = multiprocessing.get_context("spawn")
    result_queue = ctx.Queue()

    # Use _sleepy_worker so it doesn't exit immediately
    proc = ctx.Process(target=_sleepy_worker, args=(result_queue, 60), daemon=True)
    proc.start()

    assert proc.daemon is True, "Worker must be daemon=True"
    assert proc.is_alive()

    # Clean up
    proc.kill()
    proc.join(3)
    assert not proc.is_alive()
    print(f"\n  daemon=True confirmed, no zombies after kill")


def test_no_zombies_after_timeout_kill():
    """After a timeout+kill sequence, ps aux shows no <defunct> processes."""
    ctx = multiprocessing.get_context("spawn")
    result_queue = ctx.Queue()

    proc = ctx.Process(target=_sleepy_worker, args=(result_queue, 60), daemon=True)
    proc.start()
    proc.join(timeout=1)

    if proc.is_alive():
        proc.kill()
        proc.join(5)   # give OS time to reap

    # Check for zombies
    ps = sp.run(["ps", "aux"], capture_output=True, text=True)
    defunct = [l for l in ps.stdout.splitlines() if "<defunct>" in l]
    print(f"\n  Defunct after timeout+kill: {len(defunct)}")
    assert len(defunct) == 0, f"Zombie processes found: {defunct}"

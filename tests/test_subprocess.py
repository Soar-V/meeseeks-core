"""
Build 8 acceptance tests — subprocess isolation happy path.

IMPORTANT: The test meeseeks classes are defined at MODULE LEVEL here.
multiprocessing.spawn pickles function references by module path;
classes defined inside test functions cannot be pickled.
"""
from __future__ import annotations
import os
import subprocess
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel

from meeseeks import register_meeseeks, Meeseeks, summon


# ── Module-level meeseeks for subprocess tests (pickle-safe) ──────────────

@register_meeseeks
class SubprocClassify(Meeseeks):
    """Simple classification meeseeks for subprocess testing."""
    name = "subproc_classify"
    description = "Classify sentiment for subprocess test"
    tier = "thinker"
    isolation = "subprocess"   # <— real subprocess
    use_framework = False
    timeout_seconds = 60

    class Input(BaseModel):
        text: str
        index: int = 0  # track which parallel spawn this is

    class Output(BaseModel):
        sentiment: Literal["positive", "negative", "neutral"]
        index: int

    def system_prompt(self, inputs):
        return (
            f"Classify the sentiment of: '{inputs.text}'. "
            f"Return JSON with 'sentiment' (positive|negative|neutral) and 'index' ({inputs.index}). "
            "JSON only, no preamble."
        )

    def format(self, output):
        return f"[{output.index}] {output.sentiment}"


# ── Tests ─────────────────────────────────────────────────────────────────

pytestmark = pytest.mark.skipif(
    not os.environ.get("OPENROUTER_API_KEY"),
    reason="OPENROUTER_API_KEY not set",
)


def test_single_subprocess_spawn():
    """Single subprocess spawn returns a populated success envelope."""
    result = summon(
        SubprocClassify,
        SubprocClassify.Input(text="I love building with this framework!", index=0),
    )
    assert result.status == "success", f"Expected success, got: {result.reason}"
    assert result.data.sentiment in ("positive", "negative", "neutral")
    assert result.data.index == 0
    assert result.cost.total_tokens > 0
    assert result.duration_ms > 0
    assert len(result.meeseeks_id) == 8
    print(f"\n  Single spawn: {result.data.sentiment}, {result.cost.total_tokens} tokens, {result.duration_ms}ms")


def test_five_parallel_subprocess_spawns():
    """5 parallel subprocess spawns all return success."""
    texts = [
        ("I love this!", 1),
        ("This is terrible.", 2),
        ("It is what it is.", 3),
        ("Absolutely fantastic work!", 4),
        ("Could be worse, could be better.", 5),
    ]

    def _spawn(text, idx):
        return summon(SubprocClassify, SubprocClassify.Input(text=text, index=idx))

    results = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(_spawn, t, i): i for t, i in texts}
        for fut in as_completed(futures):
            results.append(fut.result())

    print(f"\n  Parallel results ({len(results)}/5):")
    for r in sorted(results, key=lambda x: x.data.index if x.data else 0):
        if r.status == "success":
            print(f"    [{r.data.index}] {r.data.sentiment} — ${r.cost.cost_usd:.5f}, {r.duration_ms}ms")
        else:
            print(f"    FAILED: {r.reason}")

    success_count = sum(1 for r in results if r.status == "success")
    assert success_count == 5, f"Only {success_count}/5 succeeded"


def test_no_zombie_processes_after_spawns():
    """After all spawns complete, no zombie meeseeks processes remain."""
    # Run one spawn to completion first
    result = summon(SubprocClassify, SubprocClassify.Input(text="test zombie check", index=99))
    assert result.status == "success"

    # Check for zombie python processes — look for <defunct> in ps aux
    ps = subprocess.run(["ps", "aux"], capture_output=True, text=True)
    defunct_lines = [l for l in ps.stdout.splitlines() if "<defunct>" in l]
    print(f"\n  Defunct processes found: {len(defunct_lines)}")
    for l in defunct_lines:
        print(f"    {l}")
    assert len(defunct_lines) == 0, f"Found {len(defunct_lines)} zombie processes: {defunct_lines}"


def test_budget_db_has_subprocess_rows():
    """Budget DB records rows from subprocess runs."""
    from meeseeks.budget import cost_breakdown
    breakdown = cost_breakdown(days=1)
    assert "subproc_classify" in breakdown, f"subproc_classify not in budget breakdown: {breakdown.keys()}"
    stats = breakdown["subproc_classify"]
    assert stats["spawns"] >= 1
    assert stats["llm_cost"] > 0
    print(f"\n  Budget: {stats['spawns']} spawns, ${stats['llm_cost']:.5f}, {stats['tokens']} tokens")

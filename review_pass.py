"""
Meeseeks-Core Build 6 Review Pass
==================================
Review items:
  1. Real spawns — thinker + worker, show full MeeseeksResult envelope
  2. Schema validation: retry behavior (§4.4) + double-failure structured envelope
  3. meeseeks cost CLI output after real spawns
  4. File tree + public API surface audit

Run with: OPENROUTER_API_KEY=... .venv/bin/python review_pass.py
"""

import os, sys, json, subprocess, textwrap
from pydantic import BaseModel
from typing import Literal

# ── bootstrap path ──────────────────────────────────────────────────────────
sys.path.insert(0, "src")

from meeseeks.registry import register_meeseeks, Meeseeks
from meeseeks.summon import summon
from meeseeks.providers.openrouter import OpenRouterProvider
from meeseeks.contracts import MeeseeksResult, TokenUsage, StructuredOutputParser
from meeseeks.budget import today_total, cost_breakdown


SEP = "\n" + "═" * 70 + "\n"

def section(title):
    print(SEP + f"  {title}" + SEP)


# ────────────────────────────────────────────────────────────────────────────
# REVIEW 1 — Real spawns: thinker + worker
# ────────────────────────────────────────────────────────────────────────────

@register_meeseeks
class ThinkerMeeseeks(Meeseeks):
    name = "review_thinker"
    description = "Classify sentiment — thinker tier review test"
    tier = "thinker"
    isolation = "inline"
    use_framework = False
    timeout_seconds = 30

    class Input(BaseModel):
        text: str

    class Output(BaseModel):
        sentiment: Literal["positive", "negative", "neutral"]
        confidence: float
        one_word_reason: str

    def system_prompt(self, inputs):
        return (
            f"Classify the sentiment of this text: '{inputs.text}'\n"
            "Return JSON with exactly these fields:\n"
            "  sentiment: 'positive' | 'negative' | 'neutral'\n"
            "  confidence: float between 0 and 1\n"
            "  one_word_reason: single word explaining the sentiment\n"
            "No preamble. JSON only."
        )

    def format(self, output):
        return f"{output.sentiment} ({output.confidence:.0%}) — {output.one_word_reason}"


@register_meeseeks
class WorkerMeeseeks(Meeseeks):
    name = "review_worker"
    description = "Summarize text with key points — worker tier review test"
    tier = "worker"
    isolation = "inline"
    use_framework = True
    timeout_seconds = 60

    class Input(BaseModel):
        text: str
        max_points: int = 3

    class Output(BaseModel):
        summary: str
        key_points: list[str]
        word_count: int

    def system_prompt(self, inputs):
        return (
            f"Summarize the following text in one sentence, then extract up to {inputs.max_points} key points.\n"
            "Return JSON with exactly:\n"
            "  summary: string\n"
            "  key_points: list of strings\n"
            "  word_count: integer (word count of the summary sentence)\n"
            "No preamble. JSON only.\n\n"
            f"TEXT:\n{inputs.text}"
        )

    def format(self, output):
        pts = "\n".join(f"  • {p}" for p in output.key_points)
        return f"**Summary:** {output.summary}\n{pts}"


def review_1():
    section("REVIEW 1 — Real spawns: thinker + worker (full envelope)")

    # Thinker
    print("── Thinker spawn: sentiment classification ──")
    r_thinker = summon(ThinkerMeeseeks, ThinkerMeeseeks.Input(
        text="I absolutely love this framework — spawning agents has never been cleaner!"
    ))
    print(json.dumps(r_thinker.model_dump(), indent=2))
    print(f"\n→ format(): {ThinkerMeeseeks().format(r_thinker.data)}")

    # Worker
    print("\n── Worker spawn: summarize with key points ──")
    r_worker = summon(WorkerMeeseeks, WorkerMeeseeks.Input(
        text=(
            "Meeseeks-Core is a Python framework for spawning ephemeral AI agents. "
            "Each meeseeks exists only to complete one task, then ceases to exist. "
            "The parent agent's context window grows with results, not with work performed. "
            "Isolation is enforced via multiprocessing spawn. The return contract is a "
            "Pydantic envelope with status, data, cost, and duration. Cost tracking is "
            "built in at every layer — LLM cost and tool cost both cross the boundary."
        ),
        max_points=3,
    ))
    print(json.dumps(r_worker.model_dump(), indent=2))
    if r_worker.status == "success":
        print(f"\n→ format():\n{WorkerMeeseeks().format(r_worker.data)}")
    else:
        print(f"\n→ spawn FAILED: {r_worker.reason}")

    return r_thinker, r_worker


# ────────────────────────────────────────────────────────────────────────────
# REVIEW 2 — Schema validation: retry + double-failure
# ────────────────────────────────────────────────────────────────────────────

def review_2():
    section("REVIEW 2 — §4.4 validate-and-retry behavior")

    provider = OpenRouterProvider()

    class StrictOutput(BaseModel):
        integer_field: int
        required_enum: Literal["alpha", "beta", "gamma"]
        nested: dict[str, str]

    # --- 2a: intentional bad first response that will pass on retry ---
    print("── 2a: First attempt returns wrong field names → retry corrects it ──")
    print("    (injecting a bad first response manually to force the retry path)\n")

    # We monkey-patch provider to return a bad response first, good on retry
    real_chat = provider.chat_with_fallback
    call_count = [0]

    def patched_chat(messages, tier, schema=None, timeout_seconds=120):
        call_count[0] += 1
        if call_count[0] == 1:
            # Bad response: wrong field names
            bad = '{"wrong_field": 42, "also_wrong": "nope"}'
            from meeseeks.contracts import TokenUsage
            fake_usage = TokenUsage(prompt_tokens=50, completion_tokens=20, total_tokens=70, cost_usd=0.0001)
            print(f"  [Attempt {call_count[0]}] Provider returning BAD response: {bad}")
            return bad, fake_usage, "mock-model"
        else:
            # Real call on retry
            print(f"  [Attempt {call_count[0]}] Provider making REAL call (retry)...")
            return real_chat(messages, tier, schema, timeout_seconds)

    provider.chat_with_fallback = patched_chat

    parser = StructuredOutputParser(schema=StrictOutput, provider=provider, tier="worker")
    test_messages = [
        {"role": "system", "content": "Return a JSON object with fields: integer_field (int), required_enum ('alpha'|'beta'|'gamma'), nested (dict of string to string)."},
        {"role": "user", "content": "Give me a sample JSON object matching the schema. JSON only, no preamble."},
    ]
    parsed, usage, reason = parser.parse_with_retry(test_messages, timeout_seconds=30)

    if parsed:
        print(f"\n  ✅ Retry SUCCEEDED. Parsed output: {parsed.model_dump()}")
        print(f"  Total cost across both attempts: ${usage.cost_usd:.5f} ({usage.total_tokens} tokens)")
    else:
        print(f"\n  Result: failure — {reason}")

    # --- 2b: double failure — both attempts return garbage → structured failure ---
    print("\n── 2b: Both attempts return garbage → structured MeeseeksResult.failure ──\n")

    call_count2 = [0]

    def always_bad_chat(messages, tier, schema=None, timeout_seconds=120):
        call_count2[0] += 1
        garbage = f"Sorry, I cannot do that. This is attempt {call_count2[0]}."
        from meeseeks.contracts import TokenUsage
        fake_usage = TokenUsage(prompt_tokens=30, completion_tokens=15, total_tokens=45, cost_usd=0.00005)
        print(f"  [Attempt {call_count2[0]}] Provider returning GARBAGE: {garbage!r}")
        return garbage, fake_usage, "mock-model"

    provider2 = OpenRouterProvider()
    provider2.chat_with_fallback = always_bad_chat

    parser2 = StructuredOutputParser(schema=StrictOutput, provider=provider2, tier="worker")
    parsed2, usage2, reason2 = parser2.parse_with_retry(test_messages, timeout_seconds=30)

    print(f"\n  Parsed output: {parsed2}")
    print(f"  Failure reason: {reason2}")
    print(f"  Cost accumulated (both failed attempts): ${usage2.cost_usd:.5f} ({usage2.total_tokens} tokens)")

    # Build the full MeeseeksResult failure envelope
    fail_result = MeeseeksResult.failure(reason=reason2, partial={"raw": "garbage"}, cost=usage2)
    print("\n  Full MeeseeksResult failure envelope:")
    print(json.dumps(fail_result.model_dump(), indent=2))


# ────────────────────────────────────────────────────────────────────────────
# REVIEW 3 — meeseeks cost CLI after real spawns
# ────────────────────────────────────────────────────────────────────────────

def review_3():
    section("REVIEW 3 — meeseeks cost CLI + SQLite data after real spawns")

    # Raw budget data
    total = today_total()
    breakdown = cost_breakdown(days=1)

    print(f"today_total(): ${total:.5f}\n")
    print("cost_breakdown(days=1):")
    print(json.dumps(breakdown, indent=2))

    print("\n── CLI output (meeseeks cost) ──")
    result = subprocess.run(
        [".venv/bin/python", "-m", "meeseeks.cli", "cost"],
        capture_output=True, text=True
    )
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)

    # Show raw SQLite rows
    print("── Raw SQLite rows (~/.meeseeks/budget.db) ──")
    import sqlite3, pathlib
    db = pathlib.Path.home() / ".meeseeks" / "budget.db"
    conn = sqlite3.connect(str(db))
    rows = conn.execute(
        "SELECT meeseeks_name, meeseeks_id, status, llm_cost_usd, total_tokens, duration_ms FROM runs ORDER BY ts DESC LIMIT 10"
    ).fetchall()
    conn.close()
    print(f"{'name':<20} {'id':<10} {'status':<10} {'cost_usd':<12} {'tokens':<8} {'ms'}")
    print("-" * 75)
    for r in rows:
        print(f"{r[0]:<20} {r[1]:<10} {r[2]:<10} ${r[3]:<11.5f} {r[4]:<8} {r[5]}")


# ────────────────────────────────────────────────────────────────────────────
# REVIEW 4 — File tree + public API surface
# ────────────────────────────────────────────────────────────────────────────

def review_4():
    section("REVIEW 4 — File tree + public API surface audit")

    print("── File tree ──")
    result = subprocess.run(
        ["find", ".", "-not", "-path", "./.git/*", "-not", "-path", "./.venv/*",
         "-not", "-path", "./__pycache__/*", "-not", "-name", "*.pyc",
         "-not", "-path", "*/__pycache__/*"],
        capture_output=True, text=True
    )
    # Sort and print
    lines = sorted(result.stdout.strip().split("\n"))
    for line in lines:
        print(line)

    print("\n── Public API surface (what you import) ──")
    api_surface = """
from meeseeks.registry import register_meeseeks, Meeseeks    # declare a meeseeks
from meeseeks.summon import summon                            # summon one
from meeseeks.contracts import MeeseeksResult, TokenUsage    # result envelope
from meeseeks.providers.openrouter import OpenRouterProvider  # model backend
from meeseeks.budget import today_total, cost_breakdown       # cost data
from meeseeks.framework_prompt import FRAMEWORK_PROMPT        # (rarely needed directly)

# Typical usage:
#   @register_meeseeks
#   class MyMeeseeks(Meeseeks):
#       name = "my_task"
#       tier = "thinker"  # or "worker" / "heavy"
#       isolation = "inline"
#       class Input(BaseModel): ...
#       class Output(BaseModel): ...
#       def system_prompt(self, inputs): ...
#       def format(self, output): ...
#
#   result = summon(MyMeeseeks, MyMeeseeks.Input(field="value"))
#   if result.status == "success":
#       print(result.data, result.cost.grand_total_usd, result.duration_ms)
"""
    print(api_surface)

    print("── OSS readiness notes ──")
    notes = [
        ("✅", "MeeseeksResult envelope — clean, Generic[T], classmethod constructors"),
        ("✅", "Registry pattern — @register_meeseeks decorator, zero boilerplate"),
        ("✅", "Pydantic v2 throughout — modern, typed"),
        ("✅", "Provider abstraction — LLMProvider base, OpenRouter impl, swappable"),
        ("✅", "Budget tracking — SQLite, per-call actuals, CLI command"),
        ("✅", "Framework prompt — constant, suppressible per-meeseeks"),
        ("⚠️ ", "StructuredOutputParser lives in contracts.py — should move to its own file"),
        ("⚠️ ", "summon() ignores isolation='subprocess' (falls back to inline) — documented TODO, not a bug"),
        ("⚠️ ", "No __init__.py top-level re-exports — `from meeseeks import summon` doesn't work yet"),
        ("⚠️ ", "OpenRouter cost field: uses `usage.cost` — verify field name against live API response"),
        ("❌", "No README yet — needed before OSS publish"),
        ("❌", "No CONTRIBUTING.md, no LICENSE file (MIT mentioned in spec, not on disk)"),
        ("❌", "No type stubs / py.typed marker — mypy users will notice"),
    ]
    print(f"{'':3} {'Item'}")
    print("-" * 70)
    for icon, note in notes:
        print(f"{icon}  {note}")

    print("\n── Verdict ──")
    print(textwrap.dedent("""
    Core engine is OSS-ready in structure. API surface is clean.
    Three things needed before public launch:
      1. Move StructuredOutputParser → contracts_parser.py or parser.py
      2. Add top-level __init__.py re-exports (4 lines)
      3. README + LICENSE (MIT) — the only real blocker for OSS credibility
    Week 2 (subprocess + Discord) can ship first. These are hour-level polish tasks.
    """))


# ────────────────────────────────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("ERROR: set OPENROUTER_API_KEY before running")
        sys.exit(1)

    print("Meeseeks-Core — Build 6 Review Pass")
    print("=" * 70)

    r_thinker, r_worker = review_1()
    review_2()
    review_3()
    review_4()

    print(SEP + "  Review complete." + SEP)

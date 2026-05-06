# Meeseeks-Core — Architecture Spec

**Version:** 0.1 (initial spec)
**Date:** 2026-05-04
**Author:** Alex (Soar) + Claude
**Audience:** Hermes (planning + implementation), Alex (reference), future contributors
**Status:** Spec locked. Ready for implementation planning.

---

## 1. Concept

A framework for spawning **single-purpose, ephemeral AI agents** ("meeseeks") that exist only to complete one task and then cease to exist. Inspired by the Mr. Meeseeks pattern from *Rick and Morty*: existence is brief by design, scope is narrow, completion is termination.

The core insight: **the parent agent's context window should grow with results, not with work performed.** A meeseeks may consume 50K tokens internally; it returns a 200-token structured payload. The parent never sees the reasoning trace.

### 1.1 Why this exists

Existing agent frameworks (AutoGPT, LangGraph, CrewAI, smolagents) either:
- Allow agents to accumulate unbounded context (AutoGPT failure mode), or
- Require heavy configuration to enforce isolation (LangGraph), or
- Conflate orchestration with model choice (most others).

Meeseeks-core enforces strict death and structured return as the primary architectural constraints. Everything else is a configuration choice on top of those two rules.

### 1.2 Target user

**Primary:** Solo developers / one-person businesses who need parallel work streams without holding multiple problems in their head.

**Secondary (private overlay):** Alex specifically, with Soar business context layered on top.

The tool is a **force multiplier for one person**, not a multi-agent collaboration system. The user is always the foreman; meeseeks are the crew.

---

## 2. Architecture Overview

### 2.1 Two-repo split

```
meeseeks-core/                   # OSS, generic, MIT license
  src/meeseeks/
    summon.py                    # the summon() primitive
    contracts.py                 # MeeseeksResult, schemas
    isolation/
      subprocess.py              # subprocess runner (workers)
      inline.py                  # no-isolation runner (thinkers)
    registry.py                  # meeseeks + toolkit registration
    budget.py                    # cost tracking
    providers/
      openrouter.py              # primary backend
      base.py                    # LLMProvider interface
    toolkits/
      research.py                # web_search, web_fetch, scrape
      comms.py                   # discord post (destructive)
  examples/
    cli_usage.py
    discord_bot.py               # reference Discord integration

hermes-meeseeks/                 # Alex's private overlay
  meeseeks/
    research_prospect.py         # PS, Med Spa, World Cup specific
    draft_outreach.py            # Soar voice, CTA patterns
    soar_morning.py              # m morning workflow
    summarize_inbox.py
  context/
    SoarContext.md               # symlinked from Obsidian
    voice_guide.md
  hermes_integration.py          # the Foreman glue
  config.yaml
```

### 2.2 The Foreman / Meeseeks split

**Hermes is the Foreman.** It already exists, runs on Alex's VPS in Python, is connected to Discord. We are *not* building a new Foreman. We are teaching Hermes to summon meeseeks.

| Hermes (Foreman) | Meeseeks |
|---|---|
| Persistent | Ephemeral (dies after one task) |
| Has memory and context that compresses over time | Stateless (gets exactly what's passed at spawn) |
| Visible in Discord, the only entity user talks to | Invisible by default (debug channel shows them) |
| Routes, plans, synthesizes results | Executes one task, returns structured data |
| Never does work itself (strict rule) | Does the actual work |

**Hard rule:** Hermes does not do meeseeks-style work inline. The moment Hermes "just quickly answers" a research question itself, it accumulates context and gets dumber. Hermes routes; meeseeks execute.

**Equally hard rule:** Meeseeks do not communicate back to Hermes during execution. They are summoned with everything they need, work, return, die. No mid-task chatter.

---

## 3. Isolation Mechanism

Two summon modes, chosen by the meeseeks's tier:

### 3.1 Inline (thinkers)

Pure LLM reasoning, no tools, no side effects. Just an isolated API call with no shared context.

- No subprocess overhead.
- Used for: classification, extraction, summarization, simple decisions.
- Roughly 90% of useful subagent work.

### 3.2 Subprocess (workers)

Full Python `multiprocessing` subprocess with `spawn` start method (NOT `fork` — `fork` inherits parent state, which leaks the thing we're trying to prevent).

- Used for: anything with tools, file ops, code execution, multi-step reasoning over external data.
- Subprocess death cleans up Python state, imports, globals.
- Subprocess death does **not** clean up external side effects (files written, API calls made). Those are handled at the toolkit layer (see §7).

### 3.3 What we are NOT building (yet)

- **Containerized isolation** (Docker, Firecracker) — overkill for personal tool, defer to v2 if needed.
- **Cloud sandboxes** (E2B, Modal) — same.
- **Long-running daemons** — violates the Meeseeks ethos. If you need persistent background work, that's a different primitive (call it a "Jerry"). Out of scope.

---

## 4. Return Contract

### 4.1 The envelope

Every meeseeks returns a `MeeseeksResult[T]`:

```python
class MeeseeksResult(Generic[T]):
    status: Literal["success", "failure", "timeout"]
    data: T | None              # populated on success
    reason: str | None          # populated on failure/timeout
    partial: dict | None        # whatever the meeseeks managed before dying
    cost: TokenUsage            # tokens + dollar cost
    duration_ms: int
    meeseeks_id: str            # short ID for debug correlation
```

### 4.2 Three rules baked into the contract

**Rule 1: Schema is mandatory at summon time.** No `summon(task)` without a return type. Every meeseeks declares an `Output` Pydantic model. Forces the summoner to think about what they actually need before spawning, which kills 80% of useless meeseeks.

**Rule 2: Hard cap on return payload size.** ~2000 tokens. If the meeseeks tries to exceed it, one retry with "your output exceeded the size limit, summarize." If retry fails, structured failure. **This is the actual mechanism that protects the parent's context window.**

**Rule 3: Cost accounting always crosses the boundary.** Token usage and wall time always come back, even on failure. Hermes uses this for budget enforcement. Tool costs (Brave search, Firecrawl, etc.) are also tracked, not just LLM cost.

### 4.3 Forbidden

The meeseeks's raw conversation history NEVER enters Hermes's context, even on failure, even for "debugging." Logs go to disk and the debug channel. The architecture collapses the moment we allow this.

### 4.4 Structured output enforcement

OpenRouter model behavior varies. The contract layer tries in this order:
1. Native structured output (tool-call-as-output for Anthropic, JSON mode for OpenAI).
2. Validate-and-retry: parse the response, if it doesn't match schema, retry once with the validation error in context.
3. After two failures: `MeeseeksResult.failure(reason="schema_mismatch", partial=raw_text)`.

---

## 5. Model Backend (OpenRouter)

### 5.1 Tiered routing

Each meeseeks declares a `tier`:

| Tier | Use case | Default model | Fallback chain |
|---|---|---|---|
| `thinker` | Cheap reasoning, extraction, classification | Claude Haiku | Llama 3.1 70B → Gemini Flash |
| `worker` | Research, drafting, multi-step | Claude Sonnet | GPT-4o → DeepSeek |
| `heavy` | Complex synthesis, code review | Claude Opus | GPT-4 Turbo |

Tier is set at meeseeks declaration. Models are config, not code. Swappable globally without touching meeseeks logic.

### 5.2 Provider abstraction

`LLMProvider` interface: `chat(messages, model, schema) → response`. OpenRouter is the first implementation. Direct Anthropic, OpenAI, Ollama can slot in later. Roughly 100 lines of code now, saves a refactor in month 2.

### 5.3 Cost tracking

OpenRouter returns actual token usage and cost in every response. Use the actuals, not estimates. Estimates drift; actuals don't.

### 5.4 Fallback policy

If primary model 429s or errors, auto-fallback to next in chain. One config file, not per-meeseeks logic. Logged to debug channel when triggered.

---

## 6. Orchestrator Decision Logic

Hermes decides, for each user message, what to do. Three layers, in order.

### 6.1 Layer 1 — Hard rules (deterministic, no LLM)

Cheap pattern matches. ~60% of messages handled here with zero token cost.

- Message starts with `/` → command (status, cancel, list active). Never spawns.
- Message <10 words AND no proper nouns/URLs → likely quick question, handle inline.
- Message contains a registered meeseeks trigger phrase → route directly.
- Message contains URL or file path → strong prior toward spawn.

### 6.2 Layer 2 — LLM router (one cheap call)

For everything that escapes Layer 1: one Haiku-tier call with structured output:

```json
{
  "action": "inline" | "spawn" | "swarm",
  "meeseeks_type": "...",
  "inputs": {...},
  "context_bundle": [...],
  "reasoning": "..."
}
```

The router has access to the **meeseeks registry** (all registered meeseeks types with descriptions, input schemas, example triggers, costs). When a new meeseeks is registered, the router automatically knows about it. No retraining.

**The router decides; it does not execute.** Hermes takes the decision and either handles inline or calls `summon()`.

### 6.3 Layer 3 — Confirmation gate

Always required before spawning. Always. Hermes posts:

```
Plan: 3 prospect researches (Anigian, Setty, Heistein)
Cost: ~$0.30 est, ~90 sec
Confirm? 👍
```

User reacts 👍 → spawn. User replies with text → router re-runs with the correction in context, asks again. **No mid-flight re-planning once meeseeks are running.**

### 6.4 Hermes's inline answer rules

Hermes can answer factually about Soar from SoarContext (when loaded into Hermes's own context). Hermes cannot do work that requires reasoning over external data. The line: "is the answer already in my head, or do I need to go look?"

### 6.5 Synthesis is Hermes's job, not the meeseeks's

Each meeseeks returns structured `Output`. Hermes reads each meeseeks's `format()` method to produce the human-readable Discord message. Meeseeks produce **data**; Hermes produces **presentation**. This division of labor is non-negotiable — it's what allows clean parallel meeseeks without them needing to coordinate.

---

## 7. Tool Design (Toolkits)

### 7.1 Toolkit pattern

Tools are grouped into **toolkits** by purpose. Each meeseeks declares which toolkits it needs.

```python
@register_toolkit
class ResearchToolkit:
    name = "research"
    tools = [web_search, web_fetch, scrape_url, search_news]
    requires_keys = ["BRAVE_API_KEY", "FIRECRAWL_API_KEY"]
    cost_profile = "per_call_external"
    destructive = False

@register_toolkit
class CommsToolkit:
    name = "comms"
    tools = [post_discord, send_telegram, send_email]
    requires_keys = ["DISCORD_BOT_TOKEN", "RESEND_API_KEY"]
    destructive = True
```

### 7.2 The destructive flag

Any toolkit marked `destructive: True` automatically triggers Hermes's confirmation gate, regardless of cost. This is the safety layer. Read-only meeseeks flow smoothly with quick 👍. Anything that writes to the world (sends email, deploys code, spends money) gets stopped at the gate every time.

### 7.3 Ship list for v1

Two toolkits only:

1. **research** — web_search via Brave, web_fetch via direct HTTP, optional scrape via Firecrawl.
2. **comms (Discord-only)** — post_discord to debug channel. Marked destructive but only target is Alex's own debug channel; can't hurt anything.

**Coding toolkit is v2.** Powerful but failure modes are scarier. Don't need it to prove the concept.

### 7.4 Per-spawn toolkit config

Defaults handle 95% of cases. Edge cases override per-spawn:

```python
summon(
    meeseeks_type="research_prospect",
    toolkits={
        "research": {
            "search_provider": "brave",
            "rate_limit": "60/hour",
            "budget_pool": "outreach_research"
        }
    }
)
```

### 7.5 Tool execution inside subprocess

When a worker spawns, toolkits instantiate inside the subprocess. Tools never share state across meeseeks. Subprocess gets:
- Tool functions with keys bound at instantiation (meeseeks never see raw keys).
- Rate limiter shared via IPC with parent (5 parallel research meeseeks don't all hit Brave's limit independently).
- Cost reporter that writes back to parent on every external call.

---

## 8. Shared Memory Layer

### 8.1 Three memory layers

```
1. FRAMEWORK PROMPT (always loaded, ~350 tokens)
   The Observe/Reason/Connect/Simulate/Test thinking pattern.
   Suppressible per-meeseeks for trivial extraction tasks.

2. CONTEXT BUNDLE (per-spawn, declared by Hermes during planning)
   Files or sections Hermes attaches at spawn time.
   Examples: SoarContext §Plastic Surgery, voice_guide.md, prior findings.
   Meeseeks reads it, uses it, dies. Doesn't persist anywhere.

3. FINDINGS LOG (write-only, append-only, dated, separate from SoarContext)
   /findings/2026-05-04/research_prospect_a3f2.json
   Structured output + metadata. Reviewed during wrapup.
   Promoted to SoarContext only by Alex, manually or via curation prompt.
```

### 8.2 Stateless by default

Meeseeks know nothing unless told. The framework prompt is the only persistent context. Everything else is opt-in per-spawn. This is what makes the OSS version usable by anyone — no Soar context bleeds into the public framework.

### 8.3 The framework prompt (locked)

```
You are a meeseeks: a single-purpose agent that exists to complete one
task and then cease to exist. Your existence is brief by design.

Apply the five-step thinking framework to your task:

1. OBSERVE (Darwin) — What does the data actually show? Catalog before
   interpreting. Don't pattern-match to assumptions.

2. REASON (Einstein) — What's the simplest explanation that fits the
   observations? Strip away unnecessary complexity.

3. CONNECT (Newton) — How do the pieces relate? What forces act on what?
   Look for the underlying structure linking observations.

4. SIMULATE (Tesla) — Before recommending action, run the scenario
   forward. What happens if we do X? What breaks?

5. TEST (Curie) — What would prove or disprove this? Build the cheapest
   experiment that reduces uncertainty.

Constraints:
- Return only the structured output requested. No preamble, no explanation
  of your process unless explicitly asked.
- If you cannot complete the task, return a structured failure with the
  reason and any partial work.
- Do not exceed your output token budget. If you would, summarize and
  flag the truncation.
- You will not run again. There is no follow-up. Complete or fail cleanly.
```

Suppressible per meeseeks via `use_framework = False`. Default `True`. Override `False` for trivial extraction/classification (saves ~$0.03 per cheap meeseeks at scale).

### 8.4 Findings log

Every successful meeseeks writes one file:

```
findings/
  2026-05-04/
    research_prospect_a3f2.json    # raw MeeseeksResult.data
    research_prospect_a3f2.md      # what Hermes posted to Discord
```

**Findings do NOT auto-load into future meeseeks.** A future meeseeks sees prior findings only if Hermes explicitly attaches them to the context bundle. This is the firewall against stale context bleed.

### 8.5 Promotion to SoarContext

Manual, by Alex, during wrapup. Hermes can suggest:

> "These 3 findings from this week look like keepers. Want me to add them to SoarContext?"

Alex 👍 or edits, Hermes appends. SoarContext is the committed branch; findings are the staging area. Alex stays the editor of the business brain.

---

## 9. Cost Tracking & Visibility

### 9.1 Status line on every Hermes response

```
$2.14 today · 4/$10 daily · 3 active
```

- `$X today`: total spent.
- `4/$10 daily`: approaching soft cap.
- `3 active`: meeseeks currently running.

At 80% of cap, status auto-bolds or adds ⚠️. Over cap, every confirmation includes overage and asks permission to exceed.

### 9.2 Soft cap policy

Daily budget is a **soft cap, ask permission to exceed**. Folded into the existing confirmation gate (no separate dialogue). One 👍 can override.

### 9.3 `/cost` command — full breakdown

```
/cost

Today: $2.14
  By meeseeks type:
    research_prospect: $1.40 (12 spawns)
    draft_outreach:    $0.62 (4 spawns)
    summarize_inbox:   $0.12 (3 spawns)
  By tool:
    LLM (claude/openai): $1.85
    Brave Search:        $0.20
    Firecrawl:           $0.09

This week: $11.40 / $50 budget
```

Plain text, tabular, no graphs. Glance at once a day.

### 9.4 Tool cost is tracked alongside LLM cost

Most frameworks ignore tool cost. Don't. Brave + Firecrawl + email APIs all add up. Every external call in a toolkit reports its cost back to the parent.

---

## 10. Discord UX

### 10.1 Two-channel pattern

**Main channel:** Clean. Meeseeks invisible. Alex talks to Hermes; Hermes replies with finished work. Confirmation gates inline.

**Debug channel:** Firehose. Every spawn, every tool call, every return, every cost. Forensic logging. Plain text, timestamped:

```
[14:32:01] SPAWN research_prospect#a3f2
           input: {prospect_name: "Anigian", vertical: "plastic_surgery"}
           model: claude-haiku, est_cost: $0.08

[14:32:14] research_prospect#a3f2 → tool_call: web_search("Dr. Anigian Plano 2026")
[14:32:18] research_prospect#a3f2 → tool_result: 8 results, top 3 summarized
[14:33:02] research_prospect#a3f2 → COMPLETE
           cost: $0.09, duration: 61s
           output: {recent_activity: [...], opening_hooks: [...]}
```

Discord's native rendering is enough. No custom UI.

### 10.2 The Discord bot is dumb on purpose

Plain text in, plain text out. No buttons, modals, embeds, slash command menus. If a UI is ever needed, it's a web link. Keeps the chat surface portable and lets us swap to Telegram later without rewriting interaction patterns.

### 10.3 Voice messages (Phase 2)

Telegram support adds voice → Whisper → Hermes routing. Walk down the street, voice-message a plan, meeseeks spawn. Underrated solo affordance. **Defer to Month 2.**

---

## 11. Meeseeks Declaration (the OSS surface)

This is the actual product. If declaration ergonomics are clean, the project succeeds. If clunky, no one adopts it.

```python
@register_meeseeks
class ResearchProspect(Meeseeks):
    name = "research_prospect"
    description = "Research a single business/practice and return structured brief"
    triggers = ["research {prospect}", "look up {practice}", "what do we know about {name}"]
    
    tier = "worker"           # thinker | worker | heavy
    toolkits = ["research"]
    isolation = "subprocess"  # inferred from tier; explicit override allowed
    
    estimated_cost_usd = 0.10
    timeout_seconds = 120
    destructive = False
    use_framework = True
    
    class Input(BaseModel):
        prospect_name: str
        vertical: Literal["plastic_surgery", "med_spa", "world_cup", "dental"]
        depth: Literal["quick", "thorough"] = "quick"
    
    class Output(BaseModel):
        prospect_name: str
        recent_activity: list[str]
        contact_info: ContactInfo
        opening_hooks: list[str]
        notes: str
    
    def system_prompt(self, inputs: Input) -> str:
        """The meeseeks-specific instructions (framework prompt is prepended automatically)."""
        return f"""
        Research the {inputs.vertical} practice "{inputs.prospect_name}".
        Find: recent activity (90 days), contact info, 3 opening hooks
        framed around the missed-revenue angle for after-hours leads.
        """
    
    def format(self, output: Output) -> str:
        """How Hermes renders this for Discord."""
        return (
            f"**{output.prospect_name}** — {output.recent_activity[0]}\n"
            f"Hook: {output.opening_hooks[0]}"
        )
```

That's the entire surface. Declare a class, register it, the framework handles spawning, isolation, contracts, costs, formatting.

---

## 12. Build Plan (3-month timeline)

### Month 1 — Core engine + first meeseeks (private value immediate)

| Week | Deliverable |
|---|---|
| 1 | `summon()` primitive: subprocess isolation + Pydantic contract + OpenRouter provider. CLI usable. |
| 2 | Two reference meeseeks: `research_prospect`, `draft_outreach`. Subprocess isolation, structured returns, budget tracking. |
| 3 | Hermes integration. Hermes summons from Discord. Confirmation gate. Debug channel. **End of week 3: Alex uses this daily.** |
| 4 | Polish, fix what broke in real use. Cost dashboard. Lock the API surface for the OSS core. |

### Month 2 — Make it real, both versions

| Week | Deliverable |
|---|---|
| 5–6 | Background/parallel spawning. Multiple meeseeks at once. `m morning` swarm. State persistence (VPS reboot resilience). Voice messages (Whisper → Hermes → meeseeks). |
| 7–8 | Open-source the core. README, docs, examples, demo Discord bot anyone can run. MIT license. Single launch post (HN Show or r/LocalLLaMA, not both). |

### Month 3 — Sharpen and harden

| Week | Deliverable |
|---|---|
| 9–10 | Build out private meeseeks library: wrapup workflow, A/B test analyzer, prospect research v2, recurring tasks. |
| 11–12 | Whatever OSS users feedback says matters. Don't plan in advance — react to real signal. |

### Scoping rule

Every feature, next 90 days, must pass two tests:
1. Does Alex use it daily?
2. Does the OSS version benefit from it?

If only #1: goes in `hermes-meeseeks` (private overlay).
If only #2: defer. Speculative OSS features kill solo projects.
If both: build once in `meeseeks-core`.

---

## 13. Locked Decisions Summary

| # | Decision | Choice |
|---|---|---|
| 1 | Isolation mechanism | Subprocess (workers) + inline (thinkers). `multiprocessing` with `spawn` start. |
| 2 | Return contract | Pydantic schema mandatory. Envelope: success/failure/timeout. 2K token cap. |
| 3 | Architecture | Hermes (existing Foreman) + meeseeks-core (new OSS library). |
| 4 | Model backend | OpenRouter, tiered (thinker/worker/heavy), provider-abstracted. |
| 5 | Orchestrator | 3-layer router: hard rules → LLM router → confirmation gate. |
| 6 | Memory | Stateless by default. Framework prompt always loaded. Per-spawn context bundle. Findings log separate from SoarContext. |
| 7 | Tools | Toolkit pattern. Declared per meeseeks. `destructive` flag triggers gate. v1 ships research + comms. |
| 8 | Cost tracking | Tool cost included. Status line on every reply. Soft cap, ask to exceed. `/cost` command. |
| 9 | UX | Two channels (main clean, debug firehose). Plain text only. Discord first, Telegram phase 2. |
| 10 | Confirmation policy | Always required for spawn. Quick 👍. Single approval covers cost overage too. |

---

## 14. Open Implementation Questions

Not architecture — these are week-1 coding decisions. Listed so Hermes can flag tradeoffs as they arise:

1. **Retry policy on meeseeks failure.** How many auto-retries before propagating failure to Hermes? Suggest: 1 retry for schema mismatch, 0 for timeout, 0 for tool errors. Tunable per meeseeks.
2. **Concurrency cap.** Max parallel meeseeks at once. Suggest: 5 workers, 20 thinkers. Soft limits with warning.
3. **State persistence format.** SQLite for meeseeks state and findings index? Or flat files? Suggest: flat files for findings, SQLite for active-meeseeks state and budget tracking.
4. **OpenRouter cost scraping cadence.** Per-call (slow but accurate) vs. periodic batch (fast but lagging). Suggest: per-call, response includes cost.
5. **Discord rate limits.** Hermes posts a lot in debug. Need to batch or throttle. Implementation detail.
6. **Hermes context compression strategy.** Every N hours or M messages, Hermes self-compresses. Need to define the trigger and the compression prompt.

---

## 15. What This Is NOT

To prevent scope creep:

- **Not Devin / not autonomous.** Meeseeks produce drafts and findings. Alex approves and acts. Meeseeks never ship code, send emails, or spend money beyond their token budget without explicit approval.
- **Not a multi-agent collaboration framework.** Meeseeks don't talk to each other. Hermes coordinates them.
- **Not a chat UI for AI.** It's an ops layer. The chat is the interface, but the value is the parallel work, not the conversation.
- **Not a replacement for Claude Code / Cursor.** Coding is a v2 toolkit. Initial v1 doesn't touch code.
- **Not LangGraph.** No graph-based workflow definitions. Meeseeks are atoms; workflows are just multiple summons.

---

## 16. Hand-off to Hermes

This document is the source of truth for the architecture. When Hermes plans implementation, the plan should reference section numbers (e.g., "implementing §4.1 envelope and §5.2 provider abstraction first").

Hermes's first job, on receiving this spec, is to produce a **week 1 implementation plan** with concrete file paths, function signatures, and acceptance criteria for the `summon()` primitive. That plan should be reviewable by Alex before any code is written.

The spec is locked but not frozen. Refinements happen through explicit edits to this document, not through verbal drift in conversations. Every change bumps the version number at the top.

---

**End of spec.**

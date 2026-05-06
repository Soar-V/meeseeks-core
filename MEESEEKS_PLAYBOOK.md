# Meeseeks Design Playbook

**Version:** 0.1
**Purpose:** The recipe for designing any meeseeks. Read this before building one.
**Audience:** Anyone extending the meeseeks library — Hermes, contributors, OSS users.
**Companion docs:** `MEESEEKS_SPEC.md` (architecture), individual `meeseeks/*.md` design specs.

---

## 1. What this document is

The architecture spec (`MEESEEKS_SPEC.md`) defines *how meeseeks run*. This playbook defines *how meeseeks are designed*. The chassis is built; this is the manual for what to put in it.

A great meeseeks is not a function that calls an LLM. It is a single-purpose agent with a tightly-bounded scope, the right tools, a synthesis-friendly output schema, explicit failure modes, and a system prompt that resists drift. Building one well is design work, not coding work. The code is the easy part.

This document gives you the eight questions to answer before you write a line of code, plus the shared conventions every meeseeks must follow.

---

## 2. The Eight Questions

Every meeseeks design spec must answer these eight questions, in order. If a question can't be answered cleanly, the meeseeks isn't ready to build — go back to thinking, not coding.

### Q1 — What single sentence describes this meeseeks?

If you can't describe it in one sentence without using "and," the scope is too broad. Split it.

**Good:** *"Researches a single business and returns a structured brief."*
**Bad:** *"Researches a business and drafts an outreach email and updates the CRM."*

The single sentence becomes the meeseeks's `description` field in the registry, which is what the LLM router sees. Vague descriptions cause routing errors. Specific ones don't.

### Q2 — What are the inputs?

Define the `Input` Pydantic schema. Required fields only. Optional fields with sensible defaults. No `**kwargs`, no `dict[str, Any]`. Every input is named, typed, documented.

Three rules:
- **Inputs are what the caller decides**, not what the meeseeks figures out. If the meeseeks needs to "decide" something based on input, that decision should be an input parameter with a `Literal` enum.
- **No business logic in defaults.** If a default value depends on context, that's a sign the input should be required.
- **Optional context bundle is separate from inputs.** Files and reference material flow through `context_bundle`, not the input schema. Keep them distinct.

### Q3 — What is the output schema, designed for synthesis?

Define the `Output` Pydantic schema. This is the contract with Julius (and with sibling meeseeks). The schema must be designed assuming Julius will:

1. Read this output programmatically (so structure matters).
2. Possibly combine it with N other meeseeks of the same type (so each output is independently complete).
3. Render it to a human via the meeseeks's `format()` method (so the data must contain everything needed for that rendering).

Three rules:
- **Lists over freeform text.** "Top 3 findings" as a `list[str]` synthesizes better than a paragraph.
- **Include source attribution where applicable.** A research meeseeks's findings should each carry a source URL. Attribution is a feature.
- **Optional fields for partial-success paths.** If a meeseeks can succeed-but-incomplete, that partial state needs explicit fields, not a missing field. Use `Optional[X] = None` with documented meaning.

### Q4 — What tools/toolkits does it minimally need?

Per spec §7. List only what's required. A research meeseeks needs `research` toolkit (web search + fetch). It does not need `comms` toolkit. Tool access is identity — extra tools dilute the meeseeks's purpose.

If a meeseeks needs no tools (pure reasoning), say so explicitly: `toolkits = []`. That's a thinker. Thinkers run inline, not in subprocess. Cheaper, faster.

If a meeseeks needs *destructive* tools (sends email, writes files, hits external APIs with side effects), flag this clearly in the spec. Destructive meeseeks always trigger Julius's confirmation gate per §6.3.

### Q5 — What tier?

Per spec §5.1: `thinker` | `worker` | `heavy`.

Pick the cheapest tier that does the job reliably. A summarization meeseeks running on Opus is wasteful. A nuanced strategic-analysis meeseeks running on Haiku is broken.

Decision heuristic:
- **Thinker** (Haiku/Llama): classification, extraction, summarization of <2000 words, simple format conversion, routing decisions.
- **Worker** (Sonnet/GPT-4o): research, drafting, multi-step reasoning, analysis over external data, anything user-facing in tone.
- **Heavy** (Opus/GPT-4): complex synthesis across many sources, creative writing requiring nuance, code review, strategic recommendations.

When unsure, start one tier lower than your gut says. Upgrade only if real-use evidence shows the cheaper tier fails.

### Q6 — What's the system prompt?

The framework prompt (§8.3) is loaded automatically. The meeseeks's own system prompt sits *below* it and constrains the meeseeks to its single purpose.

Three rules:
- **State the role narrowly.** Not "you are a helpful assistant." More like "You are a research meeseeks. Your only job is to find recent activity for one business and return it in the specified format."
- **Forbid drift explicitly.** Add a "do not" section. "Do not draft outreach. Do not recommend strategy. Do not invent facts not present in the search results. Return only what was asked."
- **Specify failure behavior.** "If you cannot find information matching the request, return a structured failure with `partial` containing what you did find, not a fabricated answer."

System prompts should be 200-500 words. Longer than that, you're trying to do too much. Shorter, you're under-specified.

### Q7 — What context bundle does it need?

Per spec §8.2: stateless by default, opt-in context per spawn.

Most meeseeks need *no* context bundle — they get everything from `Input`. Some need:
- A voice/style guide (drafting meeseeks).
- Reference data (analysis meeseeks reading prior findings).
- A schema or template (structuring meeseeks).

If a meeseeks needs context, document *exactly* what files/sections, and how Julius assembles them. Do not write meeseeks that "figure out what context they need" — that's a cost-bloated anti-pattern. Context is declared, not discovered.

For OSS: context bundles must reference files the user provides, not files specific to your business. Document the expected file shape so users can supply their own.

### Q8 — What are the failure modes?

List the three to five ways this meeseeks can fail. For each, specify the structured response.

Common failure modes:
- **No data found** (research meeseeks): return `status="failure", reason="no_data_for_query", partial={attempted_queries: [...]}`
- **Schema validation failure** (any meeseeks): handled by validate-and-retry per §4.4, returns `failure` after two attempts.
- **Tool unavailable** (toolkit meeseeks): return `status="failure", reason="tool_unavailable: <which>"`. Do not retry blindly.
- **Timeout** (long-running meeseeks): return `status="timeout", partial=<whatever was assembled>`.
- **Hallucination guard tripped** (any meeseeks): if the model returns content that fails internal sanity checks, return `failure` with the suspect output in `partial`.

Failure modes that are *not in this list* should not silently happen. If they do, that's a bug.

---

## 3. Shared Conventions (every meeseeks follows these)

### 3.1 Naming

- **Module name** = lowercase snake_case verb + noun: `research_prospect`, `draft_outreach`, `summarize_call`.
- **Class name** = PascalCase noun phrase: `ResearchProspect`, `DraftOutreach`, `SummarizeCall`.
- **Registry name** = same as module name: `research_prospect`.

No abbreviations. No clever names. The router must be able to disambiguate from the name alone.

### 3.2 File structure (one meeseeks = one file)

```
meeseeks/
  research_prospect.py
  draft_outreach.py
  ...
```

Each file contains: imports, `Input` model, `Output` model, system prompt constant, the `Meeseeks` subclass with `format()` method, registration decorator. No helpers spread across files. If a helper is large enough to extract, it goes in the meeseeks's own internal module folder.

### 3.3 Schema patterns

- **Use `Literal` over `str` for enums.** `Literal["plastic_surgery", "med_spa", "dental"]` not `str`.
- **Use `list[T]` over `List[T]`** (Python 3.9+).
- **Use `Optional[T] = None` for genuinely optional fields**, with documented meaning of `None` vs. empty.
- **All datetime fields are ISO 8601 strings**, not Python `datetime` (cleaner across subprocess boundary).
- **All cost-bearing or count fields are non-negative**: `confidence: float = Field(ge=0, le=1)`.

### 3.4 The `format()` method

Every meeseeks implements `format(self, output: Output) -> str` returning a Discord-friendly string. Julius calls this to render the result. Rules:

- **Markdown allowed** (Discord renders it).
- **Under 500 chars per meeseeks output** when synthesized as part of a swarm. If the data needs more, return a short summary in `format()` and let Julius offer "want the full output?" as a follow-up.
- **No raw JSON**, no `repr(output)`. The format method is the human-facing presentation; if it looks ugly to a human, it's wrong.

### 3.5 System prompt structure

Every meeseeks's system prompt follows this skeleton:

```
You are a [meeseeks_name] meeseeks. Your only job is to [single sentence from Q1].

You will receive: [describe input shape briefly]
You must return: [describe output shape briefly]

Process:
1. [step 1]
2. [step 2]
3. [step 3]

Constraints:
- [forbidden behaviors]
- [accuracy/honesty constraints]
- [scope boundaries — what NOT to do]

Failure handling:
- If [condition], return failure with reason "[code]"
- If [condition], return partial data with [field] populated

Format:
Return only the structured Output schema. No preamble, no explanation.
```

Every meeseeks's prompt fits this skeleton. Deviations should be deliberate and documented.

### 3.6 Hallucination resistance

Every meeseeks that consumes external data (research, analysis, summarization of provided content) must include in its system prompt:

> "Do not invent facts not present in the source material. If asked something not answerable from the available data, return a failure with `reason='insufficient_data'` and `partial` containing what you did find."

This single instruction, repeated across meeseeks, is what separates a useful library from one that quietly fabricates outputs.

### 3.7 Tier × tool combinations

Some combinations are bugs by definition:

- **Thinker + any toolkit**: thinkers don't get tools. If you need tools, you're a worker.
- **Heavy + no toolkits + simple input**: if it's a heavy-tier reasoning task with no tools, it's almost always actually a worker. Heavy is for synthesis across many sources.
- **Worker + no toolkits + no context bundle**: probably should be a thinker. Question whether the work justifies subprocess overhead.

If your design lands on one of these, reconsider the tier or the toolkit choice.

---

## 4. The Design Spec Template

Every meeseeks gets a markdown design spec at `docs/meeseeks/<name>.md` answering the eight questions. Use this template:

```markdown
# Meeseeks: <name>

**Version:** 0.1
**Tier:** thinker | worker | heavy
**Toolkits:** [list]
**Destructive:** yes | no
**Status:** draft | locked | implemented

## Q1 — Single sentence description
<one sentence>

## Q2 — Input schema
<Pydantic schema as code block, with field descriptions>

## Q3 — Output schema (designed for synthesis)
<Pydantic schema as code block, with field descriptions and synthesis notes>

## Q4 — Toolkits required
<list, with justification for each>

## Q5 — Tier
<choice + reasoning>

## Q6 — System prompt
<full prompt as a code block>

## Q7 — Context bundle
<what's needed, or "none">

## Q8 — Failure modes
<table or list of (failure mode → structured response)>

## format() method
<the Discord-rendering function as a code block>

## Notes for OSS users
<anything that needs adaptation for non-Soar use>

## Open questions
<list anything genuinely unresolved>
```

A spec is **locked** when all eight questions are answered, the schemas are valid Pydantic, and the system prompt is written. Hermes does not implement until the spec is locked.

---

## 5. Building Discipline

A few things that look like rules but are really about resisting common failure patterns:

### 5.1 One meeseeks per session

When designing a new meeseeks, work on only one at a time. Don't sketch eight half-formed specs in parallel. Land one, lock it, move to the next. Cross-contamination between half-finished specs causes scope drift.

### 5.2 The narrowest version first

If you're tempted to add "and also" features to a meeseeks during design, stop. Build the narrow version, ship it, observe real use, *then* decide if extension is needed. Most "and also" features are imagined needs, not real ones.

### 5.3 Real use beats speculation

After a meeseeks ships, dogfood it for a week before refining. Real use surfaces failure modes you cannot predict at design time. Schedule one refinement pass per meeseeks per month, driven by observed bugs and friction, not by ideas.

### 5.4 If a meeseeks's prompt grows past 500 words, the meeseeks is too broad

Long prompts are a sign you're trying to make one meeseeks do multiple jobs. Split it. Two narrow meeseeks beat one bloated one every time.

### 5.5 Schemas are forever (almost)

Once a meeseeks ships and Julius's synthesis layer is calibrated to its `Output`, changing the schema breaks the synthesis. Treat schemas as semi-permanent contracts. Add fields, don't rename or remove. If a breaking change is genuinely needed, version the meeseeks (`research_prospect_v2`).

---

## 6. Worked Example: `research_prospect`

A skeleton showing what a locked spec looks like. The full spec lives in `docs/meeseeks/research_prospect.md`.

**Q1:** Researches a single business and returns recent activity, contact info, and conversation hooks.

**Q2 Input:**
```python
class Input(BaseModel):
    business_name: str = Field(description="Exact name of the business to research")
    business_type: str = Field(description="Industry or category, used to scope search")
    location: Optional[str] = Field(default=None, description="City/region if known")
    lookback_days: int = Field(default=90, ge=1, le=365)
```

**Q3 Output:**
```python
class Activity(BaseModel):
    summary: str
    source_url: str
    date: Optional[str]

class Output(BaseModel):
    business_name: str
    found: bool
    recent_activity: list[Activity]
    contact_info: Optional[ContactInfo]
    opening_hooks: list[str] = Field(max_items=3)
    notes: Optional[str]
```

**Q4:** `["research"]` — needs web search and fetch.

**Q5:** `worker` — multi-step reasoning over external data, user-facing tone.

**Q6:** [System prompt skeleton, ~300 words]

**Q7:** None required for generic OSS use. Optional voice guide if user provides one.

**Q8:** No data found → failure with `attempted_queries`. Partial activity (some sources blocked) → success with `notes` flagging what was unavailable. Tool unavailable → failure with clear reason.

That's what a locked spec looks like. The full version becomes its own file.

---

## 7. Anti-patterns (do not do these)

A short list of things that look reasonable but produce bad meeseeks:

- **"Smart" meeseeks that figure out their own scope.** A meeseeks that "decides what kind of research to do" is two meeseeks pretending to be one.
- **Meeseeks that call other meeseeks.** Meeseeks do not summon meeseeks. Julius orchestrates. If two meeseeks need to chain, that's Julius's job to spawn them sequentially.
- **Meeseeks with stateful behavior across runs.** Each meeseeks lives once. No "remember the last research." Persistence is Julius's job (findings log, SoarContext).
- **Meeseeks that talk back to Julius mid-execution.** No streaming progress, no clarification questions. Inputs at spawn, output on completion, nothing in between.
- **Meeseeks designed without a clear failure mode for their primary risk.** Every research meeseeks must have an answer for "what if there's no data?" Every drafting meeseeks must have an answer for "what if the input is too vague?" If the spec doesn't address this, it's incomplete.
- **Generic catch-all meeseeks like `do_thing` or `general_assistant`.** Single-purpose means single-purpose. If you can't describe it in one sentence, it's not ready.

---

## 8. The Library — current and planned

The initial library covers eight common solo-operator workflows. Each has its own design spec at `docs/meeseeks/<name>.md`.

| Meeseeks | Tier | Toolkits | Purpose |
|---|---|---|---|
| `research_prospect` | worker | research | Single-business deep dive with hooks |
| `draft_outreach` | worker | — | Generate outreach copy in user's voice |
| `triage_inbox` | thinker | — | Classify emails by attention required |
| `analyze_ab_test` | worker | — | Read A/B data, recommend next iteration |
| `morning_briefing` | worker | — | Daily digest synthesizing other meeseeks |
| `wrapup_session` | worker | — | End-of-day, update context from findings |
| `summarize_call` | thinker | — | Voice memo / transcript → action items |
| `prep_for_meeting` | worker | research | Calendar event → prep brief |

Five thinkers/workers without toolkits work on text the user provides. Two workers use the research toolkit. None destructive in v1 — confirmation gate triggers come from cost, not destruction.

These are designed for OSS-friendly use. Soar-specific tuning happens via context bundles, not by editing the meeseeks themselves.

---

## 9. Versioning this document

When a convention here changes, bump the version at the top and add a changelog entry below. Conventions are sticky — every existing meeseeks was designed against the version current when it was built. Breaking changes here mean refitting the library.

### Changelog

- **0.1** (initial): eight questions, conventions, template, anti-patterns, initial library list.

---

**End of playbook.**

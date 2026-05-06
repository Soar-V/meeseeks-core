# Meeseeks: morning_briefing

**Version:** 0.1
**Tier:** worker
**Toolkits:** none
**Destructive:** no
**Dynamic toolkits:** no
**Status:** draft

---

## Q1 — Single sentence description

Plans a morning briefing by surveying available meeseeks, the user's stated goal, and pinned constraints, returning a structured execution plan that the caller (Julius) executes and synthesizes.

---

## Architectural note (read this first)

`morning_briefing` is the only **planning meeseeks** in the v1 library. It does not execute work itself; it produces a plan. The caller (Julius) reads the plan, presents one consolidated confirmation card to the user, executes the planned meeseeks, and synthesizes the results.

This pattern preserves the architecture rule from playbook §7 (*"meeseeks do not summon meeseeks"*). Julius remains the only orchestrator. The morning_briefing meeseeks is just a particularly-clever way for Julius to figure out what to spawn.

The two-stage flow:

```
1. PLAN stage:  Julius spawns morning_briefing (cheap, fast, ~$0.02)
                → returns BriefingPlan
                → Julius posts ONE confirmation card showing the full plan + cost
                → user 👍 once for the whole morning

2. EXECUTE stage: Julius reads the plan, spawns child meeseeks per the plan
                  (some parallel, some sequential)
                  → collects results
                  → Julius synthesizes into final briefing message
```

This means `morning_briefing` is fast and cheap — it's a thinking step, not a working step. The work happens after.

---

## Q2 — Input schema

```python
from typing import Literal, Optional
from pydantic import BaseModel, Field

class PinnedComponent(BaseModel):
    meeseeks_type: str = Field(
        description="Name of a meeseeks the caller wants explicitly included or excluded. Must match a registered meeseeks name."
    )
    action: Literal["include", "exclude"] = Field(
        description="include = always run this. exclude = never run this regardless of plan logic."
    )
    inputs_hint: Optional[dict] = Field(
        default=None,
        description="Partial inputs to pass when this meeseeks runs. The plan will fill in the rest. Only valid for action='include'."
    )

class AvailableMeeseeks(BaseModel):
    name: str = Field(
        description="Registered meeseeks name."
    )
    description: str = Field(
        max_length=300,
        description="One-sentence description from the meeseeks's registry entry. The planning model uses this to decide relevance."
    )
    estimated_cost_usd: float = Field(
        ge=0,
        description="Conservative cost estimate from the meeseeks's declaration."
    )
    estimated_duration_seconds: int = Field(
        ge=1,
        description="Typical wall-clock duration."
    )
    tier: Literal["thinker", "worker", "heavy"] = Field(
        description="Tier of the meeseeks. Thinkers can run inline; workers/heavy run in subprocess."
    )

class Input(BaseModel):
    goal: str = Field(
        max_length=500,
        description="The user's stated goal for this briefing. Natural language. E.g., 'Standard morning briefing — what should I focus on today?' or 'I have a board meeting at 2pm; prep me for the day.' Drives what gets included."
    )
    available_meeseeks: list[AvailableMeeseeks] = Field(
        min_items=1,
        max_items=30,
        description="The meeseeks registry available to this plan. Caller (Julius) provides this from the registry. Plan can only include meeseeks from this list."
    )
    pinned: list[PinnedComponent] = Field(
        default_factory=list,
        max_items=10,
        description="Explicit include/exclude constraints from the caller or user."
    )
    user_context: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Background on the user and their work. E.g., 'Solo founder of an AI agent service. Active outreach to plastic surgery and med spa verticals. Prepping for a Q3 fundraise.' Drives what's relevant."
    )
    today_calendar_summary: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Brief summary of today's calendar if relevant. E.g., 'Two meetings: 10am sales call with Dr. Anigian, 2pm internal review.' Lets the plan include prep_for_meeting where useful."
    )
    pending_findings_count: Optional[int] = Field(
        default=None,
        ge=0,
        description="How many findings have accumulated since last wrapup. Lets the plan suggest wrapup_session if it's been a while."
    )
    budget_cap_usd: float = Field(
        default=2.0,
        ge=0,
        description="Maximum total cost for this briefing's execution stage. The plan must stay under this. Default $2 covers a generous morning briefing."
    )
    max_duration_seconds: int = Field(
        default=180,
        ge=10,
        description="Maximum total wall-clock time. The plan respects this by parallelizing where possible. Default 3 minutes."
    )
    current_time: str = Field(
        description="ISO 8601 timestamp the meeseeks should treat as 'now'."
    )
```

**Field notes:**

- `available_meeseeks` is the registry slice the caller exposes. The planning meeseeks can only include things in this list — it cannot invent meeseeks names. This is the integrity boundary.
- `pinned` lets the caller (or user via Julius's router) hard-constrain the plan. "Always include triage_inbox" or "Skip research today, I'm on a budget." The plan must respect these.
- `user_context` is what makes the plan *relevant*. Without it, the meeseeks plans for a generic user; with it, the plan is shaped to the user's actual work.
- `today_calendar_summary` lets the plan include `prep_for_meeting` for any meetings worth prepping. Without it, prep_for_meeting won't be included even if it's available.
- `pending_findings_count` is a cheap signal for "should we run wrapup_session?" If 30+ findings have piled up, the plan should suggest wrapup; if 2, skip it.
- `budget_cap_usd` is the hard limit. The plan must stay under this even if user_context suggests doing more. Default $2 is generous for a daily briefing.

---

## Q3 — Output schema (designed for synthesis)

```python
from typing import Literal, Optional
from pydantic import BaseModel, Field

class PlannedSpawn(BaseModel):
    spawn_id: str = Field(
        description="Identifier for this spawn within the plan (e.g., 's1', 's2'). Used for sequencing references."
    )
    meeseeks_type: str = Field(
        description="Name of the meeseeks to spawn. Must be in input.available_meeseeks."
    )
    inputs: dict = Field(
        description="The inputs to pass to summon(). Must conform to that meeseeks's Input schema. The plan fills in everything required."
    )
    rationale: str = Field(
        max_length=200,
        description="One sentence on why this spawn is in the plan. Surfaces to user during confirmation."
    )
    estimated_cost_usd: float = Field(
        ge=0,
        description="Cost estimate for this individual spawn, sourced from available_meeseeks data."
    )
    parallel_group: Optional[int] = Field(
        default=None,
        description="Group identifier for parallel execution. Spawns with the same parallel_group run concurrently. None = run sequentially with no group constraint. Group 0 runs before group 1, etc."
    )
    depends_on: list[str] = Field(
        default_factory=list,
        description="spawn_ids this spawn depends on (its results are needed as inputs). Empty if no dependencies. Caller respects these for sequencing."
    )

class BriefingPlan(BaseModel):
    plan_summary: str = Field(
        max_length=400,
        description="One- to three-sentence overview of what the plan will do. Shown to user during confirmation. Plain language."
    )
    spawns: list[PlannedSpawn] = Field(
        default_factory=list,
        max_items=15,
        description="The meeseeks to spawn. Empty list = quiet morning, no work needed."
    )
    excluded_meeseeks: list[str] = Field(
        default_factory=list,
        description="Names of available meeseeks the plan deliberately did NOT include. Provided for transparency, not action."
    )
    total_estimated_cost_usd: float = Field(
        ge=0,
        description="Sum of estimated_cost_usd across spawns. Must be <= input.budget_cap_usd."
    )
    estimated_duration_seconds: int = Field(
        ge=0,
        description="Wall-clock estimate accounting for parallel groups. Must be <= input.max_duration_seconds."
    )
    confidence: Literal["high", "medium", "low"] = Field(
        description="high = goal was clear and plan is straightforward. medium = some inference about user intent. low = goal was vague; plan is best-guess."
    )

class Output(BaseModel):
    plan: BriefingPlan = Field(
        description="The plan itself. Always present, even for empty/quiet plans."
    )
    rationale_summary: str = Field(
        max_length=400,
        description="Brief explanation of the planning logic. Why these spawns, why not others. For user confirmation."
    )
    notes: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Optional meta-observations: 'Goal was vague; defaulted to standard daily briefing.' or 'Budget cap forced exclusion of prep_for_meeting; consider raising cap if meetings need prep.' Brief."
    )
```

**Synthesis notes:**

- The output IS the plan. The caller (Julius) reads `output.plan` and uses it to drive the execute stage.
- `plan_summary` is what the user sees in the confirmation card. It must be readable in 5 seconds and convey what's about to happen.
- `excluded_meeseeks` is for transparency — Julius can show "I considered these but didn't include them: X, Y" if the user asks why something wasn't run.
- `parallel_group` and `depends_on` give the caller a DAG to execute. Julius runs all spawns in group 0 in parallel, waits, then group 1, etc. `depends_on` is for fine-grained dependencies that span groups.
- `total_estimated_cost_usd` and `estimated_duration_seconds` are hard contracts — the plan **must** fit under input caps. The system prompt enforces this; the integrity guard validates it.

---

## Q4 — Toolkits required

**None.** Pure reasoning over the structured input data.

This meeseeks runs in subprocess (worker tier) but doesn't make external tool calls. Spawn cost is dominated by the LLM call itself.

---

## Q5 — Tier

**`worker`** (default model: Claude Sonnet, fallback: GPT-4o → DeepSeek).

**Reasoning:** The job involves:
- Reasoning about which meeseeks fit the user's goal
- Constructing valid inputs for selected meeseeks (must conform to their schemas)
- Optimizing for parallel execution where possible
- Respecting hard constraints (budget, duration, pinned components)
- Producing a plan the user can confirm in one glance

A thinker-tier model would produce plans that pick reasonable meeseeks but fail to construct valid inputs (filling in fields they shouldn't, missing required fields). The schema-conformance burden alone justifies worker tier.

**Why not heavy:** The reasoning is constrained — pick from a list, fill in valid inputs, respect caps. Sonnet handles this cleanly. Heavy is overkill.

**Cost calibration:**
- Standard plan, ~5 available meeseeks, clear goal: ~$0.015–$0.025 per spawn.
- Complex plan, ~10+ available meeseeks, ambiguous goal: ~$0.025–$0.040 per spawn.
- Maximum case (30 meeseeks, lots of context): ~$0.040–$0.060 per spawn.

**Conservative estimate for approval-mode logic:** `estimated_cost_usd = 0.05`.

**Important:** the planning cost is separate from the execute-stage cost. The plan itself is cheap. The work the plan triggers is what the user sees in the consolidated confirmation card.

---

## Q6 — System prompt

```
You are a morning_briefing meeseeks. Your only job is to produce an
execution plan that the caller will use to run other meeseeks. You
do NOT spawn meeseeks yourself. You produce a structured plan.

You will receive: a goal in natural language, a list of available
meeseeks (with descriptions, costs, durations, tiers), optional
pinned constraints (include/exclude), optional user context, optional
calendar summary, optional pending findings count, a budget cap, a
max duration, and the current time.

You must return: a BriefingPlan with spawns (each specifying which
meeseeks to run and with what inputs), parallel grouping for
concurrency, total cost and duration estimates that fit within caps,
and a plan summary the user can confirm at a glance.

Process:

1. Read the goal carefully. Identify what the user actually wants:
   - "Standard morning briefing" → general-purpose plan
   - "Prep me for X" → focused on a specific upcoming event
   - "Quick scan" → minimal plan, just inbox + calendar awareness
   - "Deep dive on Y" → focused work, may exceed standard scope

2. Apply pinned constraints first. Includes are mandatory; excludes
   are forbidden regardless of relevance. If an include conflicts
   with the budget cap, prioritize the include and trim elsewhere.

3. Survey available_meeseeks. For each, ask:
   - Does this meeseeks help with the goal?
   - Do I have the inputs needed to call it productively?
   - Is the cost justified for what it produces?

4. Build the spawn list. For each included meeseeks:
   - Construct a complete inputs dict matching the meeseeks's Input
     schema. Use information from user_context, today_calendar_summary,
     and any pinned inputs_hint. If you can't construct valid required
     inputs, do not include that meeseeks; note it in `excluded_meeseeks`
     with reason.
   - Write a one-sentence rationale.

5. Decide parallel groups:
   - Independent spawns (no shared inputs, no result dependencies)
     can run in parallel — assign them the same parallel_group integer.
   - Spawns whose inputs depend on another spawn's output go in a
     later group (or use depends_on for fine-grained sequencing).
   - Default to group 0 unless there's a reason to sequence.
   - Common pattern: triage_inbox (group 0) parallel with research_prospect
     calls (group 0), then prep_for_meeting (group 1) using their results.

6. Verify caps:
   - Sum of estimated_cost_usd <= budget_cap_usd. If exceeded, drop
     the lowest-priority spawn(s) and note in `notes`.
   - Effective duration (max across parallel groups, sum across
     sequential groups) <= max_duration_seconds. If exceeded, drop
     spawns or move sequential to parallel where independence allows.

7. Generate plan_summary (under 400 chars). Plain language description
   of what's about to happen. Example:
   "Triage inbox, research 3 active prospects in parallel, prep for
   the 2pm meeting with Dr. Anigian. ~$0.45, ~90 seconds."

8. Set confidence honestly:
   - high: goal was clear, plan is obvious, all constraints fit easily.
   - medium: some inference needed about what the user wanted.
   - low: goal was vague or constraints forced significant trimming.

Constraints:

- Do not include meeseeks not in available_meeseeks. The list is the
  contract.
- Do not exceed budget_cap_usd or max_duration_seconds. Hard caps.
- Do not invent inputs you don't have grounding for. If a meeseeks
  requires a specific input (e.g., research_prospect needs business_name)
  and you can't derive that from user_context or calendar, do not
  include that meeseeks.
- Do not include 'wrapup_session' in a morning briefing unless
  pending_findings_count is at least 10. Wrapups are for end of session,
  not start.
- Do not pad the plan. A plan with 2 well-chosen spawns beats a plan
  with 6 marginal ones. Quality over coverage.
- Do not exclude pinned-include meeseeks. They go in the plan even
  if you'd otherwise have skipped them.

Failure handling:

- If goal is too vague to plan ('do stuff'), return a plan with one
  reasonable default (e.g., triage_inbox if available) and notes
  flagging the vague goal.
- If pinned constraints conflict (include X, but X requires inputs
  not derivable, AND budget can't support X), include X anyway with
  the best-guess inputs and flag the issue in notes — pinned takes
  priority.
- If budget_cap_usd is too low to include even one meaningful spawn,
  return an empty plan with notes explaining the cap is too tight.
- If available_meeseeks is empty, return an empty plan with notes.

Format:

Return only the structured Output schema. The plan must be valid:
inputs conform to schemas, costs sum correctly, parallel groups
are well-formed.
```

**Word count: ~600 words.** Slightly over the 500-word target. Acceptable: the planning logic is intricate enough that abbreviated guidance produces brittle plans.

---

## Q7 — Context bundle

**None required.**

All context flows through input fields (`user_context`, `today_calendar_summary`, `available_meeseeks`). The meeseeks doesn't read separate files.

**Note for callers:** the burden of providing good context is on the caller (Julius). A morning_briefing call with sparse `user_context` and no `today_calendar_summary` produces a generic plan. With rich context, the plan is sharply tailored. Worth Julius spending a few cents pre-fetching calendar data and assembling user context before calling morning_briefing.

---

## Q8 — Failure modes

| # | Failure mode | Detection | Structured response |
|---|---|---|---|
| 1 | Empty available_meeseeks | `len(input.available_meeseeks) == 0` | Return success with empty plan and notes explaining nothing's available. Pre-LLM check. |
| 2 | Budget cap below cheapest meeseeks cost | `min(m.estimated_cost_usd) > budget_cap_usd` | Return success with empty plan, notes recommending higher cap. |
| 3 | Schema validation failure | Output malformed | Framework validate-and-retry per §4.4. Returns failure after two attempts. |
| 4 | Plan references unknown meeseeks_type | Internal check: every spawn.meeseeks_type must be in available_meeseeks | `status="failure"`, `reason="unknown_meeseeks_in_plan"`, `partial` includes the suspect spawn. |
| 5 | Plan exceeds budget cap | Internal check: `sum(s.estimated_cost_usd) > budget_cap_usd` | `status="failure"`, `reason="plan_exceeds_budget"`, retry once with stricter prompt. |
| 6 | Plan exceeds duration cap | Computed: max across parallel groups + sum across sequential > max_duration_seconds | `status="failure"`, `reason="plan_exceeds_duration"`, retry once. |
| 7 | Pinned include not in plan | Internal check: every pinned.meeseeks_type with action="include" must appear in spawns | `status="failure"`, `reason="pinned_violation"`, retry once. |
| 8 | Pinned exclude appears in plan | Internal check: no pinned.meeseeks_type with action="exclude" may appear in spawns | `status="failure"`, `reason="pinned_violation"`. |
| 9 | Spawn inputs don't conform to target meeseeks's Input schema | Validate each spawn.inputs against the registered Input schema | `status="failure"`, `reason="invalid_spawn_inputs"`, `partial` includes the offending spawn. |
| 10 | Circular depends_on | Internal check: no cycle in the dependency graph | `status="failure"`, `reason="circular_dependency"`. |
| 11 | Timeout | Spawn exceeds 60s (this is a planning meeseeks, should never approach this) | `status="timeout"`, `partial` contains whatever was assembled. |

**Failure modes #4 through #10 are integrity guards** specific to this meeseeks's structure. Without them, the caller could receive a "valid-looking" plan that explodes at execute time:
- #4 prevents hallucinated meeseeks names.
- #5/#6 enforce the budget contract.
- #7/#8 enforce the pinned-constraint contract.
- #9 is the most important — a plan with malformed spawn inputs would fail at execute time, after the user has already approved. The check should validate against actual meeseeks Input schemas before returning the plan.
- #10 prevents deadlock at execute stage.

**Implementation note:** failure mode #9 requires the framework to have access to all meeseeks Input schemas at validation time. This is possible because the registry knows them; it's a matter of plumbing.

---

## format() method

```python
def format(self, output: Output) -> str:
    """Render Output as a Discord-friendly summary for Julius's synthesis."""
    plan = output.plan
    
    lines = []
    lines.append("**Morning briefing plan**")
    lines.append("")
    lines.append(plan.plan_summary)
    
    if not plan.spawns:
        lines.append("")
        lines.append("_Empty plan — nothing scheduled._")
        if output.notes:
            lines.append(f"_{output.notes}_")
        return "\n".join(lines)
    
    # Spawn list with grouping visible
    lines.append("")
    lines.append(
        f"**Will run {len(plan.spawns)} meeseeks** "
        f"(~${plan.total_estimated_cost_usd:.2f}, "
        f"~{plan.estimated_duration_seconds}s)"
    )
    
    # Group spawns by parallel_group for display
    groups = {}
    for spawn in plan.spawns:
        g = spawn.parallel_group if spawn.parallel_group is not None else -1
        groups.setdefault(g, []).append(spawn)
    
    for group_id in sorted(groups.keys()):
        spawns = groups[group_id]
        if group_id == -1:
            # Sequential, no group
            for spawn in spawns:
                lines.append(f"• `{spawn.meeseeks_type}` — {spawn.rationale}")
        else:
            # Parallel group
            if len(spawns) > 1:
                lines.append(f"_(parallel, group {group_id}):_")
            for spawn in spawns:
                lines.append(f"• `{spawn.meeseeks_type}` — {spawn.rationale}")
    
    # Confidence flag if not high
    if plan.confidence != "high":
        lines.append("")
        lines.append(f"_Plan confidence: {plan.confidence}_")
    
    if output.notes:
        lines.append("")
        lines.append(f"_{output.notes}_")
    
    return "\n".join(lines)
```

**Output contract:** under 1000 chars typically. This format is what Julius shows in the consolidated confirmation card. The user reads the plan, sees the cost and duration, and reacts 👍 once for the entire morning's work.

---

## Notes for OSS users

- **This meeseeks is special — it doesn't do work, it plans work.** The caller (Julius or your own orchestration layer) reads the returned plan and executes it. If you skip the execute stage, nothing actually runs.
- **Julius integration pattern:**
  1. User says "morning briefing" or similar.
  2. Julius assembles `available_meeseeks` from registry, pulls calendar summary, gathers user_context.
  3. Julius spawns morning_briefing → gets plan back.
  4. Julius posts ONE confirmation card showing plan + total cost + duration.
  5. User 👍.
  6. Julius executes the plan: spawns each child meeseeks per the parallel/sequential structure, collects results.
  7. Julius synthesizes results into the final briefing message and posts.
- **The user only sees one confirmation card.** Even though the plan triggers 5+ child spawns, the user approves once for the whole thing. Each child spawn does NOT get its own confirmation card — that's the entire point of consolidating into a plan.
- **`available_meeseeks` is the contract.** The plan can only include meeseeks the caller exposes. Want to restrict morning_briefing to certain types? Pass a filtered list.
- **Pinned constraints are how users override defaults.** "Always include triage_inbox" or "skip research today" — these go in `pinned`. Julius can build these from user preferences or config.
- **Budget cap is your safety net.** Default $2 is generous; tighten to $0.50 for cheap mornings, raise to $5 for deep-work mornings. The plan respects the cap or fails with a clear reason.
- **Don't expect this to plan multi-day workflows.** One spawn = one briefing. For week-planning, run multiple times or build a separate `weekly_planning` meeseeks.

---

## Open questions

1. **Should the plan include "if X, then Y" conditional spawns** (e.g., "run prep_for_meeting only if today_calendar has external meetings")? Currently all conditionals must be resolved at plan time. Conditional execution would be more flexible but adds complexity. Defer.

2. **Should there be a "plan revision" mode** where the user pushes back on the plan ("skip the research, focus on inbox") and the meeseeks revises? Currently the user can only 👍/reject. Revision support would require a second meeseeks call, but improves UX. Could be implemented at the Julius layer (re-call with updated pinned constraints) without changing this spec.

3. **Should the plan support cost-tier preferences** (e.g., "prefer thinker meeseeks today, I want it cheap")? Currently the plan picks tier based on what the meeseeks declares. User-driven tier preference would be a useful dial. Defer until real demand.

4. **Should there be templates** like `template="quick_scan"` or `template="deep_focus"` that bias the plan? The hybrid approach (goal + pinned) handles most of this. Templates would be syntactic sugar. Defer.

5. **Should it suggest meeseeks to add to the registry** (e.g., "your goal involves email drafting but no draft_outreach is registered")? Useful but adds scope. Defer.

---

**End of spec.**

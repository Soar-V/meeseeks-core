# Meeseeks: wrapup_session

**Version:** 0.1
**Tier:** worker
**Toolkits:** none
**Destructive:** no
**Dynamic toolkits:** no
**Status:** draft

---

## Q1 — Single sentence description

Reviews the findings produced by other meeseeks during a session, suggests which ones to promote to long-term context, and produces a narrative session log.

---

## Q2 — Input schema

```python
from typing import Literal, Optional
from pydantic import BaseModel, Field

class FindingRecord(BaseModel):
    finding_id: str = Field(
        description="Unique ID for this finding. Typically the meeseeks_id from the original spawn (e.g., 'a3f2b8c1'). Used to map promotions back to source."
    )
    meeseeks_type: str = Field(
        description="Which meeseeks produced this finding. E.g., 'research_prospect', 'analyze_ab_test'."
    )
    timestamp: str = Field(
        description="ISO 8601 timestamp when the finding was produced."
    )
    summary: str = Field(
        max_length=500,
        description="Brief description of what this finding contains. Caller's responsibility to extract — typically the format() output from the original meeseeks."
    )
    structured_data: Optional[dict] = Field(
        default=None,
        description="The original Output dict from the meeseeks, if available. Lets the wrapup reason about specifics. None if only summary is provided."
    )
    user_approved: Optional[bool] = Field(
        default=None,
        description="True if the user took action on this finding (acknowledged result, used a draft, accepted research). False if rejected. None if no signal. Helps the wrapup weight what mattered."
    )
    cost_usd: Optional[float] = Field(
        default=None,
        ge=0,
        description="Cost of producing this finding. For session-cost reporting in the log."
    )

class Input(BaseModel):
    session_label: str = Field(
        description="What this session is. Could be 'today', 'this week', '2026-05-04 morning', or a project name. Drives the narrative tone and timeframe references."
    )
    session_start: str = Field(
        description="ISO 8601 timestamp when the session began. Used for log header."
    )
    session_end: str = Field(
        description="ISO 8601 timestamp when the session ended. Used for log header. Defaults to current_time if absent at caller layer."
    )
    findings: list[FindingRecord] = Field(
        default_factory=list,
        max_items=100,
        description="Findings to review. Empty list = nothing produced this session, meeseeks returns a 'quiet session' summary."
    )
    existing_context_summary: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Brief summary of what's already in long-term context (e.g., SoarContext). Helps the meeseeks identify which findings are genuinely new vs. duplicate. Skip if no long-term context exists yet."
    )
    user_focus: Optional[str] = Field(
        default=None,
        max_length=300,
        description="What the user was trying to accomplish this session, if known. E.g., 'Cold outreach for plastic surgery vertical' or 'Preparing for Q3 board meeting.' Drives narrative emphasis."
    )
    promotion_threshold: Literal["conservative", "balanced", "aggressive"] = Field(
        default="balanced",
        description="conservative = only suggest promotions for findings clearly worth keeping. balanced = default judgment. aggressive = suggest more promotions, accept higher false-positive rate."
    )
    current_time: str = Field(
        description="ISO 8601 timestamp the meeseeks should treat as 'now'."
    )
```

**Field notes:**

- The meeseeks does NOT read filesystem. Caller (Julius) reads the findings log files, extracts the relevant data, and passes structured `FindingRecord` objects. This preserves the isolation principle from spec §3.
- `summary` is required because every finding must have a one-glance description. `structured_data` is optional — when present, the meeseeks can reason about specifics; when absent, it works with the summary alone.
- `user_approved` is the highest-leverage signal for promotion suggestions. A finding the user acted on is much more likely to be worth keeping than one that was generated and ignored. Caller populates this from interaction history (e.g., Discord reaction history, email-sent flags).
- `existing_context_summary` is what prevents promotion of duplicates. If "Dr. Anigian opened Plano in March 2026" is already in SoarContext, suggesting it again is noise. Caller provides a brief summary of long-term context for diff-checking.
- `promotion_threshold` is the dial for how aggressive the suggestions are. Default "balanced" works for most users; tighten for tidy long-term context, loosen if you want to capture more.
- `max_items=100` caps cost. A typical day produces 5-20 findings; a week 30-80; rare to exceed 100.

---

## Q3 — Output schema (designed for synthesis)

```python
from typing import Literal, Optional
from pydantic import BaseModel, Field

class PromotionSuggestion(BaseModel):
    finding_id: str = Field(
        description="ID of the finding being suggested for promotion. Maps back to input."
    )
    suggested_destination: str = Field(
        description="Where in long-term context this should go. E.g., 'SoarContext > PS Active Prospects > Dr. Anigian' or 'voice_guide.md > example outreach drafts'. Caller interprets the path."
    )
    proposed_text: str = Field(
        max_length=500,
        description="The actual text to add. Already formatted for the destination. User can paste verbatim or edit."
    )
    rationale: str = Field(
        max_length=200,
        description="Why this is worth promoting. One sentence. References the finding's significance."
    )
    confidence: Literal["high", "medium", "low"] = Field(
        description="high = clearly novel and useful. medium = probably worth keeping. low = marginal call, user should review."
    )

class SessionTheme(BaseModel):
    theme: str = Field(
        max_length=150,
        description="A pattern observed across multiple findings. E.g., 'Outreach response rates were higher for missed-revenue framing across 3 prospects.' Concrete, grounded."
    )
    finding_ids: list[str] = Field(
        description="Which findings support this theme. At least 2."
    )

class Output(BaseModel):
    session_label: str = Field(description="Echoes input.session_label.")
    findings_count: int = Field(
        ge=0,
        description="Total findings reviewed. May be 0 for quiet sessions."
    )
    total_cost_usd: float = Field(
        ge=0,
        description="Sum of cost_usd across findings, when provided. 0 if no cost data."
    )
    summary: str = Field(
        max_length=600,
        description="Two- to four-sentence overall summary of what happened this session and what mattered. The orientation field."
    )
    themes: list[SessionTheme] = Field(
        default_factory=list,
        max_items=5,
        description="Patterns observed across findings. Empty if findings are too disparate or too few for themes."
    )
    promotion_suggestions: list[PromotionSuggestion] = Field(
        default_factory=list,
        max_items=10,
        description="Specific promotions the user should consider. Ordered by confidence (high first). Capped at 10 to keep review tractable."
    )
    skipped_findings: list[str] = Field(
        default_factory=list,
        description="finding_ids the meeseeks reviewed but doesn't suggest promoting. Surfaced so the user knows nothing was overlooked. May be long; that's fine."
    )
    session_log: str = Field(
        max_length=4000,
        description="Narrative session log in markdown. Suitable for writing to a file, posting to NotebookLM, archiving as a session record. Includes header (date, session label), summary, key activity, decisions, and notes."
    )
    notes: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Optional meta-observations: 'Most findings were research; consider running A/B tests next session to validate hypotheses.' Brief."
    )
```

**Synthesis notes:**

- `summary` is the scan-and-orient field — what happened, what mattered. Read in 10 seconds.
- `themes` are cross-finding patterns. Different from individual findings — themes emerge only from multiple data points. Empty for sparse sessions.
- `promotion_suggestions` are the actionable output. Each is a copy-paste-ready text + destination. The user reviews 5-10 of these in 60 seconds and approves or rejects.
- `skipped_findings` exists so the user knows the meeseeks looked at everything, not just the promotions. Transparency about what was reviewed and not selected.
- `session_log` is a markdown narrative the caller can write to disk, append to a journal, push to NotebookLM, or post to Discord. The meeseeks generates the text; the caller decides what to do with it.

---

## Q4 — Toolkits required

**None.** Pure reasoning over the structured input data.

This meeseeks runs in subprocess (worker tier requires it for isolation), but doesn't make external tool calls. Spawn cost is dominated by the LLM call, which can be substantial for sessions with many findings.

---

## Q5 — Tier

**`worker`** (default model: Claude Sonnet, fallback: GPT-4o → DeepSeek).

**Reasoning:** The job involves:
- Reasoning across many heterogeneous findings (different meeseeks types, different domains)
- Identifying themes that span multiple findings (cross-cutting pattern detection)
- Generating well-formatted promotion suggestions with proposed_text already shaped for the destination
- Writing a coherent narrative session log

This exceeds thinker capabilities. A Haiku-tier model can list findings but produces flat summaries without theme detection or sharply-targeted promotion suggestions. The narrative log specifically needs worker-tier writing quality to be useful as a session record.

**Why not heavy:** Heavy is overkill for routine session wrap-up. Reserve Heavy for genuinely complex synthesis (e.g., quarterly reviews across hundreds of findings).

**Cost calibration:**
- Quiet session, 0-3 findings: ~$0.04–$0.06 per spawn.
- Typical session, 10-20 findings: ~$0.08–$0.15 per spawn.
- Heavy session, 50-100 findings: ~$0.20–$0.40 per spawn.

**Conservative estimate for approval-mode logic:** `estimated_cost_usd = 0.50` (covers max case, errs high so auto-approve doesn't surprise on heavy sessions).

---

## Q6 — System prompt

```
You are a wrapup_session meeseeks. Your only job is to review findings
produced during a session, identify which ones are worth promoting to
long-term context, and produce a narrative session log.

You will receive: a session label, time bounds, a list of findings
(each with id, type, summary, optional structured data, and approval
signal), an optional summary of existing long-term context, optional
user focus, a promotion threshold (conservative/balanced/aggressive),
and the current time.

You must return: a session summary, themes spanning multiple findings,
promotion suggestions with proposed text, a list of skipped findings,
and a narrative session log in markdown.

Process:

1. Read all findings first. Establish: what did the user spend the
   session on, what kinds of meeseeks ran, what produced action.

2. Identify themes — patterns observed across two or more findings.
   Themes are not summaries of individual findings; they're observations
   that emerge from looking at multiple findings together. Examples:
   - "Three prospect research findings all noted recent expansion
     activity in the same vertical, suggesting market timing."
   - "Outreach drafts across multiple variants converged on the
     missed-revenue framing as the strongest angle."
   Skip themes that are speculative or that span only one finding.

3. For each finding, decide whether to suggest promotion. A promotion-
   worthy finding has these properties:
   - The information is genuinely new (not already in
     existing_context_summary, when provided).
   - The information has lasting value (not a transient observation).
   - The user took action on it OR it represents a durable insight
     about the work.
   Apply the promotion_threshold:
   - conservative: only findings that clearly meet all three criteria.
     Most findings are skipped.
   - balanced: findings that meet two of three or are strong on one
     dimension. Default judgment.
   - aggressive: findings that meet at least one criterion strongly.
     More promotions, more user-review burden.

4. For each promoted finding, generate a PromotionSuggestion:
   - suggested_destination: where in long-term context this fits.
     Be specific. "SoarContext" alone is useless; "SoarContext > 
     Active Prospects > Dr. Anigian" is actionable.
   - proposed_text: the exact text to add, already formatted for
     the destination. Should be paste-ready.
   - rationale: one sentence on why this is worth keeping.
   - confidence: honest about how clear-cut the call is.

5. Build skipped_findings list — the IDs of findings reviewed but
   not promoted. This is for transparency, not exclusion. The user
   should be able to see "the meeseeks looked at all 23 findings;
   here are the 4 it suggests promoting."

6. Generate the summary (2-4 sentences). What did the session
   accomplish, what mattered, what's next. Concrete.

7. Generate the session_log (markdown, under 4000 chars). Structure:
   ```
   # Session: <label>
   <date range>

   ## Summary
   <2-4 sentence summary>

   ## Key Activity
   - Finding 1 (one-line): <what happened>
   - Finding 2: <what happened>
   ...

   ## Themes
   <if any themes were identified>

   ## Suggested Promotions
   <numbered list of promotion suggestions, brief>

   ## Cost
   <total cost if available>

   ## Notes
   <any meta-observations>
   ```
   This is a record. The user may file it, paste it into NotebookLM,
   or use it for review. Make it readable on its own.

Constraints:

- Do not invent findings not present in input. If findings is empty,
  return findings_count=0 and a "quiet session" summary. Status success.
- Do not suggest promotions for findings that duplicate
  existing_context_summary content. Check before suggesting.
- Do not promote every finding. Even on aggressive threshold, some
  findings are transient (a draft that wasn't sent, a research result
  that confirmed what was already known).
- Do not generate proposed_text that's a verbatim copy of the
  finding's summary. The proposed_text should be shaped for the
  destination — e.g., a finding's summary might be "Researched Dr.
  Anigian, found Plano expansion" but the proposed_text for SoarContext
  is "Dr. Anigian opened Plano location March 2026 — capacity expansion."
- Do not pad the session_log with filler. A 3-finding session produces
  a short log. Padding produces useless records.

Failure handling:

- If findings is empty (quiet session): return success with
  findings_count=0, summary noting the quiet session, empty
  promotion_suggestions, brief session_log explaining nothing
  notable happened.
- If existing_context_summary is provided but seems unrelated to
  findings, proceed and note in the meta-output.
- If structured_data is missing on most findings (only summaries),
  still produce useful output — themes and promotions can work from
  summaries alone, just with lower granularity.

Format:

Return only the structured Output schema. The session_log field
must be valid markdown that renders cleanly when written to a .md file.
```

**Word count: ~570 words.** Slightly over the 500-word target. Acceptable: the process steps are tightly numbered and the structured log template earns its inclusion (without it, the model produces inconsistent log formats).

---

## Q7 — Context bundle

**None required.**

The meeseeks operates entirely from `Input`. The `existing_context_summary` field carries any reference to long-term context directly in the input, so no separate file is needed.

**Note for callers:** if existing context is large (e.g., a full SoarContext.md), the caller should summarize it down to ~2000 chars before passing as `existing_context_summary`. Passing the full file would inflate spawn cost without proportional benefit — the meeseeks only needs to know "what's already there at a high level" to detect duplicates.

---

## Q8 — Failure modes

| # | Failure mode | Detection | Structured response |
|---|---|---|---|
| 1 | Empty findings list | `len(input.findings) == 0` | Return success with `findings_count=0`, "quiet session" summary, empty promotions, brief log. Pre-LLM check, no spawn cost. |
| 2 | Schema validation failure | Output malformed | Framework validate-and-retry per §4.4. Returns failure after two attempts. |
| 3 | Promotion suggestions reference non-existent finding_ids | Internal check: every PromotionSuggestion.finding_id must exist in input.findings | `status="failure"`, `reason="orphan_promotion"`, `partial` includes the suspect suggestion. |
| 4 | Themes reference non-existent finding_ids | Same check, on themes | `status="failure"`, `reason="orphan_theme"`, `partial` includes the suspect theme. |
| 5 | Skipped + promoted IDs don't account for all findings | Internal check: `set(promoted_ids ∪ skipped_ids) == set(input.findings_ids)` | `status="failure"`, `reason="findings_mismatch"`, retry once. |
| 6 | session_log exceeds 4000 chars | Schema validation catches this | Framework retries with "shorten the log" instruction. After two retries, fail. |
| 7 | Hallucination in proposed_text | Internal check: proposed_text references specifics not present in the finding's summary or structured_data | `status="failure"`, `reason="hallucination_guard"`, `partial` flags suspect suggestion. |
| 8 | Timeout | Spawn exceeds 180s (extended for heavy sessions) | `status="timeout"`, `partial` contains whatever was assembled. |

**Failure modes #3, #4, and #5 are integrity guards** specific to this meeseeks's structure:
- #3 and #4 prevent suggestions or themes from referencing IDs the meeseeks invented.
- #5 ensures every finding gets accounted for — either promoted or skipped, no silent drops. This is critical for trust: the user needs to know "all 23 findings were reviewed."

**Failure mode #7 is the most important guard** — proposed_text that hallucinates content is the failure mode that would erode trust most. The user sees a paste-ready promotion, pastes it into SoarContext, only to discover later that it contains fabricated details. The check: every concrete claim in proposed_text must trace back to the finding's summary or structured_data.

---

## format() method

```python
def format(self, output: Output) -> str:
    """Render Output as a Discord-friendly summary for Julius's synthesis."""
    lines = []
    
    # Header with session label and counts
    lines.append(f"**Session wrapup: {output.session_label}**")
    lines.append(
        f"_{output.findings_count} findings reviewed · "
        f"${output.total_cost_usd:.2f} total cost_"
    )
    
    if output.findings_count == 0:
        lines.append("")
        lines.append(output.summary)
        return "\n".join(lines)
    
    # Summary
    lines.append("")
    lines.append(output.summary)
    
    # Themes if present
    if output.themes:
        lines.append("")
        lines.append("**Themes:**")
        for theme in output.themes[:3]:
            lines.append(f"• {theme.theme}")
        if len(output.themes) > 3:
            lines.append(f"_+ {len(output.themes) - 3} more themes_")
    
    # Promotion suggestions — the actionable part
    if output.promotion_suggestions:
        lines.append("")
        lines.append(f"**Promotions to review ({len(output.promotion_suggestions)}):**")
        # Show top 3 inline; rest is "review to see all"
        for sug in output.promotion_suggestions[:3]:
            confidence_marker = ""
            if sug.confidence == "low":
                confidence_marker = " _(low confidence)_"
            lines.append(f"• → `{sug.suggested_destination}`{confidence_marker}")
            lines.append(f"  _{sug.rationale}_")
        if len(output.promotion_suggestions) > 3:
            lines.append(f"_+ {len(output.promotion_suggestions) - 3} more — full list in session log_")
    else:
        lines.append("")
        lines.append("_No promotions suggested for this session._")
    
    # Skipped count (transparency, not enumeration)
    if output.skipped_findings:
        lines.append(f"_{len(output.skipped_findings)} findings reviewed and skipped (transient or duplicate)._")
    
    if output.notes:
        lines.append("")
        lines.append(f"_{output.notes}_")
    
    return "\n".join(lines)
```

**Output contract:** under 1000 chars in typical cases. The session_log field is NOT included in the format output — it's a separate artifact the caller writes elsewhere (file, NotebookLM, etc.). Discord users get a concise summary; the long-form log lives in its appropriate destination.

---

## Notes for OSS users

- **The meeseeks doesn't touch your filesystem.** Caller (Julius, or a workflow script) reads findings from disk and passes them as structured input. Meeseeks reasons; caller persists.
- **`existing_context_summary` is the highest-leverage optional field.** Without it, the meeseeks may suggest promoting findings that duplicate what's already in long-term context. Pass a 1-2K summary of your long-term context for sharper suggestions.
- **`user_approved` flag on findings is high-value signal.** If your caller can track which findings the user acted on (e.g., outreach drafts that got sent, research results that got referenced), populate this field. The meeseeks heavily weights approved findings as worth keeping.
- **`promotion_threshold` controls noise.** Start at "balanced" (default) for most use cases. Tighten to "conservative" if your long-term context tends to bloat; loosen to "aggressive" if you're early-stage and want to capture broadly.
- **The session_log is a deliverable.** Treat the `session_log` string field as if the meeseeks wrote a markdown document for you. Save it, paste it, archive it — the caller decides. Common patterns:
  - Write to `sessions/2026-05-04.md` for archival.
  - Push to NotebookLM as a source document.
  - Post to a `#session-log` Discord channel.
  - Email to yourself for end-of-day review.
- **Run cadence: end of day, end of week, or end of project.** Daily wrapup catches transient details; weekly wrapup surfaces themes; project wrapup distills lasting insights. The `session_label` and time bounds adapt to whatever cadence you pick.

---

## Open questions

1. **Should the meeseeks support multi-session wrapups** (e.g., "wrap up the last 7 days, treating each day as a sub-session")? Currently flat — all findings treated as one session. Multi-session would add hierarchy but complicate the schema. Defer until real demand.

2. **Should `proposed_text` support multiple destination formats** (e.g., one version for SoarContext, one for NotebookLM)? Currently one destination per suggestion. Could expand if users have multiple long-term stores. Defer.

3. **Should there be a "follow-up suggestions" output** (e.g., "based on this session, consider running prep_for_meeting for tomorrow's call about X")? Useful but expands scope. Could be a separate `plan_next_session` meeseeks if real demand.

4. **Should the session_log structure be configurable** (e.g., user provides a template)? Currently fixed structure. Configurability adds flexibility but inconsistency. Defer; users who want custom format can post-process the structured output.

---

**End of spec.**

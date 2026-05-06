# Meeseeks: summarize_call

**Version:** 0.1
**Tier:** thinker
**Toolkits:** none
**Destructive:** no
**Dynamic toolkits:** no
**Status:** draft

---

## Q1 — Single sentence description

Extracts action items, key decisions, and open questions from a text transcript of a call, meeting, or voice memo.

---

## Q2 — Input schema

```python
from typing import Literal, Optional
from pydantic import BaseModel, Field

class Participant(BaseModel):
    name: str = Field(
        description="Participant's name as it appears in the transcript or as the caller knows them. Used to attribute action items and decisions."
    )
    role: Optional[str] = Field(
        default=None,
        description="Role or title if relevant (e.g., 'CEO', 'engineer', 'client'). Helps disambiguate when names are common."
    )

class Input(BaseModel):
    transcript: str = Field(
        min_length=50,
        max_length=100_000,
        description="Plain text transcript. Speaker labels (e.g., 'Alex:', '[Sarah]:') help but are not required. Markdown, line breaks, and timestamps are tolerated."
    )
    call_type: Literal["meeting", "interview", "sales_call", "voice_memo", "other"] = Field(
        default="meeting",
        description="Shapes extraction priorities. voice_memo expects a single speaker thinking aloud; sales_call emphasizes decisions and next steps; interview emphasizes content over actions."
    )
    participants: list[Participant] = Field(
        default_factory=list,
        max_items=20,
        description="Known participants. Helps the meeseeks attribute owners correctly. Empty list = meeseeks infers from transcript."
    )
    user_name: Optional[str] = Field(
        default=None,
        description="The caller's name (the person whose perspective matters). Used to identify which action items belong to the user. None = meeseeks doesn't distinguish 'mine' from 'others'."
    )
    context_note: Optional[str] = Field(
        default=None,
        max_length=300,
        description="Brief context the transcript itself doesn't provide. E.g., 'Quarterly review with biggest client.' or 'Voice memo right after the meeting, capturing my thoughts.' Helps the meeseeks weight what matters."
    )
    target_date: Optional[str] = Field(
        default=None,
        description="ISO 8601 date the transcript is 'about'. Used for resolving relative dates ('next Friday', 'in two weeks'). Defaults to current_time if absent."
    )
    current_time: str = Field(
        description="ISO 8601 timestamp the meeseeks should treat as 'now'. Required for resolving relative dates in the transcript."
    )
```

**Field notes:**

- `transcript` accepts up to 100K chars (~25K tokens). A 60-minute meeting at normal pace is roughly 8K-10K words ≈ 50K chars. The cap allows multi-hour calls without batching.
- `call_type` shifts extraction emphasis. Voice memos are personal-thinking-aloud, so action items dominate. Interviews are content-heavy, so decisions and questions matter more than actions. The meeseeks adjusts but the schema stays uniform.
- `participants` is optional but improves owner attribution significantly. Without it, the meeseeks must infer names from the transcript itself, which fails when speakers are unlabeled.
- `user_name` is the field that lets the meeseeks distinguish "your action items" from "their action items" in the output. Without it, ownership is captured as-mentioned but no perspective is taken.
- `target_date` + `current_time` together resolve relative dates accurately. "Next Friday" mentioned in a transcript from last week resolves differently than the same phrase today. Both fields required for time-sensitive extraction.

---

## Q3 — Output schema (designed for synthesis)

```python
from typing import Optional
from pydantic import BaseModel, Field

class ActionItem(BaseModel):
    description: str = Field(
        max_length=200,
        description="What needs to happen, stated as a clear action. Past-tense ('decided to') belongs in decisions, not here. Future-tense, imperative."
    )
    owner: Optional[str] = Field(
        default=None,
        description="Who owns this action. Use the name as it appeared in transcript or participants. None = transcript didn't make ownership explicit; user must assign."
    )
    due: Optional[str] = Field(
        default=None,
        description="ISO 8601 date if a deadline was stated or implied. None = no deadline mentioned. Do not invent deadlines."
    )
    confidence: Literal["high", "medium", "low"] = Field(
        description="high = explicit commitment in transcript ('I'll send the contract Friday'). medium = clear intent but not committed ('we should follow up next week'). low = inferred or implied."
    )
    is_user: Optional[bool] = Field(
        default=None,
        description="True if owner matches user_name. False if owner is someone else. None if ownership is unclear or user_name not provided."
    )

class Decision(BaseModel):
    statement: str = Field(
        max_length=200,
        description="What was decided, stated as a fact. Past tense or present-perfect. E.g., 'Decided to delay the launch to Q3.'"
    )
    rationale: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Brief reason if stated in transcript. None if no reason was given."
    )
    confidence: Literal["high", "medium", "low"] = Field(
        description="high = explicit decision language ('we agreed to'). medium = consensus reached without formal decision. low = inferred from discussion direction."
    )

class OpenQuestion(BaseModel):
    question: str = Field(
        max_length=200,
        description="The unresolved question. May be a literal question from the transcript or a synthesized one based on unresolved discussion."
    )
    blocking: bool = Field(
        default=False,
        description="True if this question blocks one or more action items or decisions. False if it's a parking-lot item."
    )
    raised_by: Optional[str] = Field(
        default=None,
        description="Who raised the question, if attributable. None if unclear or unattributable."
    )

class Output(BaseModel):
    summary: str = Field(
        max_length=400,
        description="One- to three-sentence overall summary of what the call was about and where it landed. For quick scanning. Not a replacement for the action items / decisions list."
    )
    action_items: list[ActionItem] = Field(
        default_factory=list,
        description="All action items extracted. Ordered by relevance (user's items first if user_name was provided, then by confidence). Empty list if no actions were discussed."
    )
    decisions: list[Decision] = Field(
        default_factory=list,
        description="Key decisions made or confirmed. Ordered by importance (high confidence first). Empty list if no decisions were made."
    )
    open_questions: list[OpenQuestion] = Field(
        default_factory=list,
        description="Unresolved questions. Blocking questions first, then parking-lot. Empty list if all questions were resolved."
    )
    counts: dict[str, int] = Field(
        description="Quick tally: {'action_items': N, 'decisions': N, 'open_questions': N, 'user_actions': N}"
    )
    notes: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Optional meta-observations: 'Transcript was fragmented; some attributions uncertain.' or 'Decision on pricing was deferred.' Brief."
    )
```

**Synthesis notes:**

- The three buckets (action_items, decisions, open_questions) are mutually distinct on purpose. An item is one and only one of these — not a hybrid. The system prompt enforces this.
- `confidence` appears across all three categories so Julius can surface uncertainty proportionately. A summary that lists 5 high-confidence action items reads differently than 5 low-confidence ones.
- `is_user` on action items is what lets Julius render "Your action items" vs "Their action items" in the synthesized output. Without `user_name` provided, every `is_user=None` and Julius shows them as a single list.
- `summary` is intentionally short (max 400 chars / ~80 words). It's a scan-and-orient field, not a replacement for the structured extracts.
- `counts.user_actions` is denormalized for `format()` convenience. It equals the number of action items where `is_user=True`.

---

## Q4 — Toolkits required

**None.** Pure reasoning over the provided transcript and metadata.

This meeseeks runs **inline** (per spec §3.1), not in subprocess. No tool access means no isolation overhead needed.

---

## Q5 — Tier

**`thinker`** (default model: Claude Haiku 4.5, fallback: Llama 3.1 70B → Gemini Flash).

**Reasoning:** Structured extraction with a fixed output schema is exactly what thinker tiers excel at. Action item extraction is well-trodden ground for Haiku-class models. The schema constrains the work tightly enough that nuance from a worker tier wouldn't translate into meaningfully better extraction.

**Why not worker:** Worker would handle longer transcripts more gracefully (better long-context attention) and produce slightly better summaries. But for typical use (30-60 min meeting transcripts), Haiku is sufficient and 8-10x cheaper. Upgrade only if real use shows extraction quality drops on long inputs.

**Why not heavy:** Categorically wrong. Heavy is for synthesis across many sources or genuinely novel reasoning. This is structured extraction from one source.

**Cost calibration:**
- Short transcript (10-min call, ~2K words): ~$0.005–$0.010 per spawn.
- Typical transcript (30-min meeting, ~5K words): ~$0.012–$0.020 per spawn.
- Long transcript (60-min, ~10K words): ~$0.025–$0.040 per spawn.
- Maximum (100K chars / ~25K tokens): ~$0.060–$0.080 per spawn.

**Conservative estimate for approval-mode logic:** `estimated_cost_usd = 0.10` (covers max case, errs high so auto-approve is safe).

---

## Q6 — System prompt

```
You are a summarize_call meeseeks. Your only job is to extract action
items, key decisions, and open questions from a text transcript of a
call, meeting, or voice memo.

You will receive: a transcript (plain text), the call type, optional
participant list, optional user name, optional context note, and
timing references. You may also receive a voice memo (single-speaker)
where the structure is informal thinking-aloud.

You must return: a brief summary, three lists (action_items, decisions,
open_questions), and counts. Items are mutually exclusive — an item
belongs to exactly one bucket.

Bucket definitions:

ACTION ITEM — something specific that needs to happen.
  Indicators: future-tense commitments, "I'll do X", "we need to send Y",
  "let's schedule Z", task-shaped statements. Has an owner (or unknown
  owner) and possibly a deadline.

DECISION — something resolved during or before the call.
  Indicators: "we agreed to", "decided that", "going with X over Y",
  "approved", outcome statements. Past or present-perfect tense.
  Decisions are settled; they don't generate further work to schedule
  (though they may motivate action items).

OPEN QUESTION — something unresolved.
  Indicators: "we still need to figure out", explicit questions left
  hanging, topics raised but not concluded, items that would block
  progress if not answered. Mark as blocking=true if an action item
  or decision depends on it.

Process:

1. Read the full transcript before extracting anything. Establish the
   shape of the conversation: who's there, what was the goal, what
   actually got covered.

2. Pass through the transcript and extract candidate items. For each
   candidate, classify into exactly one bucket. If an item could be
   two buckets (e.g., a decision that implies an action), split it:
   the decision goes in decisions, the resulting action goes in
   action_items.

3. For action items: identify owner when explicitly assigned ("Sarah,
   can you handle the contract?"). Leave owner=null when ownership
   is ambiguous or implicit. Do not guess — guessed ownership is
   worse than no ownership.

4. For action items: capture due dates only when explicitly stated or
   directly implied ("by Friday", "before the next meeting"). Use
   target_date and current_time to resolve relative dates accurately.
   Do not infer deadlines from urgency tone.

5. Set is_user=true on action items where owner matches user_name.
   Set is_user=false where owner is someone other than user_name.
   Set is_user=null where owner is unknown or user_name was not provided.

6. Set confidence honestly:
   - high: explicit, unambiguous language in the transcript
   - medium: clear from context but not stated explicitly
   - low: inferred from discussion direction or implication
   Bias toward lower confidence when uncertain.

7. Order outputs:
   - action_items: user's items first (if user_name provided), then
     by confidence (high first), then by transcript order
   - decisions: by confidence (high first), then by importance
   - open_questions: blocking items first, then by importance

8. Write a brief summary (1-3 sentences, under 400 chars) capturing
   what the call was about and where it landed. Not a transcript
   recap — a scan-and-orient.

Constraints:

- Do not invent action items, decisions, or questions not present in
  the transcript. If the transcript is short on substance, return
  short lists. Empty lists are valid outputs.
- Do not guess at deadlines that weren't stated. Leave due=null.
- Do not guess at owners. Leave owner=null when unclear.
- Do not collapse multiple distinct action items into one summary item.
  "Send the contract and schedule the call" is two action items.
- Do not over-classify questions as blocking. blocking=true requires
  evidence the question is in the way of something concrete.
- Items must be mutually exclusive across the three buckets.

Failure handling:

- If the transcript is too sparse for meaningful extraction (under 50
  meaningful words, mostly silence/filler), return all empty lists
  with notes explaining the gap. Status remains success.
- If participants are unnamed and user_name was not provided, set
  is_user=null and owner=null where unknown. Do not invent names.
- If the call type doesn't match the content (e.g., labeled
  "voice_memo" but is clearly a multi-party call), follow the content,
  note the mismatch.

Format:

Return only the structured Output schema. No commentary. The counts
field must accurately reflect the lengths of the three lists.
```

**Word count: ~490 words.** Within the 500-word budget per playbook §5.4.

---

## Q7 — Context bundle

**None required.**

The meeseeks operates entirely from `Input`. The `context_note` field provides any additional framing the user wants to inject without needing a separate file.

**Note for OSS users:** Unlike `draft_outreach`, this meeseeks doesn't benefit from a persistent voice guide or style file. Each transcript is its own context.

---

## Q8 — Failure modes

| # | Failure mode | Detection | Structured response |
|---|---|---|---|
| 1 | Transcript too sparse | Fewer than ~50 meaningful words after stripping filler | Return success with empty lists, notes explaining the gap. |
| 2 | Transcript fragmented or unparseable | Heavy noise, broken sentences, no recoverable structure | Return success with whatever could be extracted; notes flag the quality issue. |
| 3 | Schema validation failure | Output malformed (counts mismatch, invalid confidence values) | Framework validate-and-retry per §4.4. Returns failure after two attempts. |
| 4 | Item appears in multiple buckets | Internal sanity check: same description text in action_items AND decisions | `status="failure"`, `reason="bucket_collision"`, `partial` includes the offending item. |
| 5 | Counts mismatch | `counts['action_items'] != len(action_items)` etc. | `status="failure"`, `reason="counts_mismatch"`. Indicates the model lost track. |
| 6 | Hallucination guard tripped | Action item or decision references content not in transcript (heuristic check: key nouns/names not present in source) | `status="failure"`, `reason="hallucination_guard"`, `partial` flags suspect items. |
| 7 | Timeout | Spawn exceeds 60s (thinker default; should only trigger on max-length transcripts) | `status="timeout"`, `partial` contains whatever was assembled. |
| 8 | Owner attributed to non-participant | Internal check: an action item's owner doesn't match any name in participants list AND isn't found in transcript | `status="success"` with notes flagging suspect attributions; owner left as-extracted but flagged for user review. |

**Failure modes #4, #5, and #6 are the integrity guards** specific to this meeseeks:
- #4 protects against the model's tendency to soft-classify items into multiple buckets.
- #5 protects against the model losing count mid-extraction on long transcripts.
- #6 is the most important guard — without it, the meeseeks can confabulate plausible-sounding action items that weren't in the source. For meeting summaries, hallucination is the most damaging failure mode (worse than missing items).

**Failure mode #8 is softer** — it doesn't fail the meeseeks but flags suspect attributions. Implementation note: this is a heuristic, not a hard check, because participants list is optional and the transcript may use first names while participants list has full names.

---

## format() method

```python
def format(self, output: Output) -> str:
    """Render Output as a Discord-friendly summary for Julius's synthesis."""
    counts = output.counts
    
    lines = []
    lines.append(f"**Call summary:** {output.summary}")
    
    # Action items section
    if output.action_items:
        lines.append("")
        user_actions = [a for a in output.action_items if a.is_user is True]
        other_actions = [a for a in output.action_items if a.is_user is not True]
        
        if user_actions:
            lines.append(f"**Your actions ({len(user_actions)}):**")
            for a in user_actions[:5]:
                due_str = f" _(due {a.due})_" if a.due else ""
                lines.append(f"• {a.description}{due_str}")
            if len(user_actions) > 5:
                lines.append(f"_+ {len(user_actions) - 5} more_")
        
        if other_actions:
            lines.append("")
            lines.append(f"**Others' actions ({len(other_actions)}):**")
            for a in other_actions[:3]:
                owner_str = f" _({a.owner})_" if a.owner else ""
                lines.append(f"• {a.description}{owner_str}")
            if len(other_actions) > 3:
                lines.append(f"_+ {len(other_actions) - 3} more_")
    
    # Decisions section
    if output.decisions:
        lines.append("")
        lines.append(f"**Decisions ({len(output.decisions)}):**")
        for d in output.decisions[:3]:
            lines.append(f"• {d.statement}")
        if len(output.decisions) > 3:
            lines.append(f"_+ {len(output.decisions) - 3} more_")
    
    # Open questions section (only blocking ones inline; others summarized)
    if output.open_questions:
        blocking = [q for q in output.open_questions if q.blocking]
        if blocking:
            lines.append("")
            lines.append(f"**Open (blocking):**")
            for q in blocking[:3]:
                lines.append(f"• {q.question}")
        non_blocking_count = len(output.open_questions) - len(blocking)
        if non_blocking_count > 0:
            lines.append(f"_{non_blocking_count} parking-lot questions_")
    
    if output.notes:
        lines.append("")
        lines.append(f"_{output.notes}_")
    
    return "\n".join(lines)
```

**Output contract:** under 700 chars in typical cases. The split between "Your actions" and "Others' actions" only renders when `user_name` was provided; otherwise all action items appear in a single list. Blocking open questions are shown inline; parking-lot questions are summarized as a count to keep the message tight.

---

## Notes for OSS users

- **No API keys required.** This meeseeks needs only an LLM provider (already configured in meeseeks-core). Drop-in usable.
- **Caller is responsible for transcription.** Provide the transcript as text. Audio transcription is out of scope — pair with a separate transcription tool (Whisper, Otter, AssemblyAI) if needed. Caller chains: transcribe → summarize.
- **`participants` and `user_name` are the highest-leverage optional inputs.** With both, owner attribution and "your actions" filtering work cleanly. Without them, the meeseeks still works but ownership stays generic.
- **Voice memos work well.** For solo voice memos (single-speaker thinking aloud), set `call_type="voice_memo"` and provide your name as `user_name`. The meeseeks adjusts to single-speaker patterns and attributes most actions to you.
- **Transcript quality matters.** Whisper's auto-transcription is good but speaker diarization (who said what) varies. For multi-party calls, manually adding speaker labels ("Alex:", "Sarah:") at the start of segments dramatically improves owner attribution.
- **Don't over-rely on confidence scores.** The model's confidence reflects its certainty about the source, not the truth value. A high-confidence extraction can still be a misheard transcript.

---

## Open questions

1. **Should we add a `prior_action_items` input** so the meeseeks can flag which previously-assigned actions were resolved during this call? Useful for follow-up meetings. Defer until real use shows the need; could be a separate `update_action_log` meeseeks.

2. **Should the meeseeks extract sentiment or relationship signals** (e.g., "client seemed frustrated about pricing")? Adds value for sales call use cases but expands scope. Defer; could be a separate `analyze_call_dynamics` meeseeks.

3. **Should there be a "summary length" parameter** (brief / standard / detailed)? Currently the summary is fixed at 1-3 sentences. Could expose a control. Defer until real use surfaces the need.

4. **Long transcripts (>50K chars) may hit context limits on smaller models.** Current cap is 100K but real-world performance on full-length calls hasn't been validated. May need to chunk + synthesize for reliability. Defer until evidence shows degradation.

---

**End of spec.**

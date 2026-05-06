# Meeseeks: triage_inbox

**Version:** 0.1
**Tier:** thinker
**Toolkits:** none
**Destructive:** no
**Dynamic toolkits:** no
**Status:** draft

---

## Q1 — Single sentence description

Classifies a batch of emails by attention required (urgent / needs_response / fyi / ignore) using only metadata, with a one-sentence reason per classification.

---

## Q2 — Input schema

```python
from typing import Literal, Optional
from pydantic import BaseModel, Field

class EmailMetadata(BaseModel):
    id: str = Field(
        description="Unique identifier passed through unchanged. Caller's responsibility to maintain (Gmail message ID, IMAP UID, custom ID, etc.)."
    )
    sender: str = Field(
        description="From field. Email address preferred; display name acceptable. Raw value, not normalized."
    )
    subject: str = Field(
        description="Subject line as received. Empty string is valid."
    )
    received_at: str = Field(
        description="ISO 8601 timestamp when the email was received. Used for recency weighting."
    )
    is_reply: bool = Field(
        default=False,
        description="True if this is part of an existing thread (Re:, In-Reply-To header). Affects classification — replies to user-initiated threads are higher priority."
    )
    has_attachments: bool = Field(
        default=False,
        description="True if any attachments. Sometimes signals importance."
    )
    in_user_contacts: Optional[bool] = Field(
        default=None,
        description="True if sender is in user's address book. Strong signal for needs_response. None if unknown."
    )

class Input(BaseModel):
    emails: list[EmailMetadata] = Field(
        min_items=1,
        max_items=100,
        description="Batch to classify. Cap at 100 to keep cost bounded; caller should chunk larger batches."
    )
    user_context: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Brief description of who the user is and what 'urgent' means for them. E.g., 'I run a solo consultancy; client emails matter most. Vendor sales pitches are noise.'"
    )
    current_time: str = Field(
        description="ISO 8601 timestamp the meeseeks should treat as 'now'. Required for accurate recency reasoning across timezones and async runs."
    )
```

**Field notes:**

- `id` flows through unchanged so the caller can map classifications back to their email source. The meeseeks doesn't care about the format.
- **Body content is intentionally excluded.** Metadata-only is the design constraint that keeps this meeseeks cheap, fast, and privacy-respecting. The classification is "should the user look at this," not "summarize this email."
- `user_context` is the only place the meeseeks gets personalized signal. Without it, classifications fall back to generic patterns ("client-sounding email = needs_response"). With 1-2 sentences of context, accuracy jumps significantly.
- `current_time` is required, not derived. Subprocess clocks may differ from user expectations, and "urgent" is time-relative ("received 6 hours ago" matters differently at 9am vs 11pm).
- `max_items=100` caps cost. A typical morning triage of 30-50 emails fits cleanly. Larger volumes need batching at the caller (Julius) level.

---

## Q3 — Output schema (designed for synthesis)

```python
from typing import Literal
from pydantic import BaseModel, Field

class Classification(BaseModel):
    id: str = Field(
        description="Same id as input. Mapping anchor."
    )
    priority: Literal["urgent", "needs_response", "fyi", "ignore"] = Field(
        description="""
        urgent         = needs attention within hours; client emergencies, time-bound asks, security alerts
        needs_response = real reply expected within ~48 hours; not blocking, but on the user's plate
        fyi            = informational, no action needed; status updates, confirmations, non-critical announcements
        ignore         = newsletters, marketing, automated notifications, spam, non-actionable noise
        """
    )
    reason: str = Field(
        max_length=140,
        description="One sentence (under 140 chars) explaining the classification. Plain language. Used by user to verify or override."
    )
    confidence: Literal["high", "medium", "low"] = Field(
        description="high = unambiguous signal. medium = reasonable inference. low = best guess; user should review."
    )

class Output(BaseModel):
    classifications: list[Classification] = Field(
        description="Same length as input.emails. Order preserved."
    )
    counts: dict[str, int] = Field(
        description="Tally by priority for quick summary: {'urgent': 2, 'needs_response': 5, 'fyi': 8, 'ignore': 15}"
    )
    notes: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Optional meta-observations about the batch (e.g., 'Unusual volume of vendor pitches today'). Brief."
    )
```

**Synthesis notes:**

- `classifications` preserves input order and IDs so Julius (and the caller) can join back to the original email source without ambiguity.
- `counts` is denormalized on purpose — it's used in `format()` for a quick at-a-glance summary without iterating the full list. Cheap to produce, expensive to omit.
- `confidence` lets Julius signal uncertainty: "I flagged 3 emails as urgent, but 1 was low-confidence — you may want to verify." This is what separates a useful triager from one that's loud about its bad guesses.
- `reason` is capped at 140 chars (one tweet) to enforce brevity. The reason is for the user's verification, not the meeseeks's self-justification.

---

## Q4 — Toolkits required

**None.** Pure reasoning over the metadata supplied in `Input`.

This meeseeks runs **inline** (per spec §3.1), not in subprocess. No tool access means no isolation overhead needed. Spawn is a single LLM call, latency under 2 seconds for typical batches.

---

## Q5 — Tier

**`thinker`** (default model: Claude Haiku 4.5, fallback: Llama 3.1 70B → Gemini Flash).

**Reasoning:** Classification with a fixed enum output is exactly what thinkers excel at. Haiku-tier models handle 4-way classification with reasons reliably when the schema is tight and the system prompt is specific.

**Why not worker:** Worker tiers (Sonnet/GPT-4o) would produce slightly more nuanced reasons but at 8-10x the cost for marginal quality improvement. Triage is a high-volume, low-stakes-per-item task — cost discipline matters.

**Why not heavy:** Categorically wrong tier. There's no synthesis here, no novel reasoning, just pattern-matching against an enum.

**Cost calibration:**
- Typical batch (30 emails): ~$0.003–$0.008 per spawn (one Haiku call, ~3K input tokens, ~1K output tokens).
- Maximum batch (100 emails): ~$0.012–$0.020 per spawn.
- Per-email cost: roughly $0.0001–$0.0002. Cheap enough to triage daily without thought.

**Conservative estimate for approval-mode logic:** `estimated_cost_usd = 0.02` (covers maximum batch, errs high so auto-approve doesn't surprise).

---

## Q6 — System prompt

```
You are a triage_inbox meeseeks. Your only job is to classify a batch of
emails by attention required, using only metadata, and produce a brief
reason for each classification.

You will receive: a list of email metadata records (sender, subject,
timestamp, is_reply, attachment flag, contact-list membership), an optional
user_context describing who the user is, and the current time.

You must return: one Classification per input email, preserving order
and IDs, plus aggregate counts.

The four priority levels:

URGENT — needs attention within hours.
  Indicators: explicit time-bound asks ("by EOD", "before tomorrow's call"),
  apparent emergencies, security/account alerts, replies in active threads
  the user initiated, senders flagged in user_context as critical.

NEEDS_RESPONSE — real reply expected within ~48 hours; not blocking.
  Indicators: questions from known contacts, vendor/client correspondence
  requiring acknowledgment, scheduling requests, follow-ups on user's prior
  outreach.

FYI — informational, no reply needed.
  Indicators: confirmations of orders/payments, calendar invites the user
  already accepted, status updates from systems the user follows, BCC'd
  copies, "here's the report you asked for" deliverables.

IGNORE — non-actionable noise.
  Indicators: marketing emails, newsletters, automated notifications without
  action items, sales pitches, spam, cold outreach the user didn't solicit.

Process:

1. For each email, examine sender, subject, and metadata flags.
2. Apply user_context if provided — it overrides general patterns.
3. Pick the priority that best fits, biased toward LOWER urgency when
   ambiguous. Over-classifying as urgent is a worse failure than
   under-classifying.
4. Write a one-sentence reason (under 140 chars). Be concrete: name the
   signal you used. "Cold sales pitch from vendor" beats "looks like spam".
5. Set confidence: high if the signal is unambiguous (newsletter, replied
   thread from known contact), medium for reasonable inference, low when
   guessing.

Constraints:

- Use ONLY the metadata provided. Do not invent content from email bodies
  you cannot see. The reason must be defensible from sender/subject alone.
- Do not assume malice or importance without signal. A subject line of
  "Re: contract" from an unknown sender is not automatically urgent.
- Bias toward IGNORE for unknown senders with marketing-typical subjects.
  Better to miss one cold lead than flood the user with noise.
- Bias toward NEEDS_RESPONSE (not URGENT) when uncertain about urgency.
  Urgent is a strong claim and should require strong signal.
- Do not generate reasons longer than 140 characters. Hard cap.
- Do not invent priority levels. Use exactly: urgent, needs_response,
  fyi, ignore.

Failure handling:

- If an email's metadata is so sparse that no defensible classification
  is possible, return priority="fyi" with confidence="low" and a reason
  noting the lack of signal. Do not skip emails.
- If user_context contradicts general patterns, follow user_context.

Format:

Return only the structured Output schema. No preamble, no narration.
The classifications list must have the same length and order as the input.
```

**Word count: ~470 words.** Within the 500-word budget per playbook §5.4.

---

## Q7 — Context bundle

**None required.**

The `user_context` field on `Input` carries any personalization needed. There's no separate file or reference document.

**Note for OSS users:** populating `user_context` is optional but high-value. A 1-2 sentence description of "what matters to me" dramatically improves classification accuracy. Without it, the meeseeks falls back to generic patterns that work but are noisier.

Example user_contexts that work well:
- *"I run a solo consultancy. Client emails matter most. Vendor pitches are noise unless they're about my existing tools."*
- *"I'm a hiring manager at a 20-person startup. Candidate replies and recruiter introductions are high priority. Internal HR system notifications are FYI."*
- *"I'm the technical co-founder. PRs, customer bug reports, and investor emails are urgent. Marketing newsletters are always ignore."*

---

## Q8 — Failure modes

| # | Failure mode | Detection | Structured response |
|---|---|---|---|
| 1 | Sparse metadata, no defensible classification | Email has empty subject AND unknown sender AND no flags | Return `priority="fyi"`, `confidence="low"`, `reason` notes the gap. Do not skip — every input gets a classification. Status remains `success`. |
| 2 | All emails in batch are unclassifiable | Whole batch is structurally degraded (e.g., all empty subjects) | Return classifications with all `confidence="low"`, `notes` flagging the batch quality. Status `success` — meeseeks did its job. |
| 3 | Schema validation failure | Model returns malformed Output (wrong list length, invalid priority value) | Handled by framework per §4.4 validate-and-retry. Returns `failure` after two attempts with `partial` containing raw output. |
| 4 | Timeout | Spawn exceeds 60s (thinker default; should never trigger for batches ≤ 100) | `status="timeout"`, `partial` contains whatever was assembled. |
| 5 | Counts don't match classifications | Internal sanity check: `sum(counts.values()) != len(classifications)` | `status="failure"`, `reason="counts_mismatch"`. Indicates the model lost track mid-batch. |
| 6 | Order/ID mismatch | Internal sanity check: output IDs don't match input IDs in order | `status="failure"`, `reason="id_order_mismatch"`. Preserving order is contractual. |

**Failure modes #5 and #6 are the integrity guards** for this specific meeseeks. Without them, a model that drops or duplicates an email mid-batch would silently corrupt the output. The framework should run both checks before returning success.

---

## format() method

```python
def format(self, output: Output) -> str:
    """Render Output as a Discord-friendly summary for Julius's synthesis."""
    counts = output.counts
    total = sum(counts.values())
    
    if total == 0:
        return "**Inbox triage:** no emails to classify."
    
    # Header line with counts
    lines = [
        f"**Inbox triage:** {total} emails — "
        f"🔴 {counts.get('urgent', 0)} urgent · "
        f"🟡 {counts.get('needs_response', 0)} needs response · "
        f"⚪ {counts.get('fyi', 0)} fyi · "
        f"⚫ {counts.get('ignore', 0)} ignore"
    ]
    
    # List urgent items inline (these are the ones the user actually needs to see)
    urgent_items = [c for c in output.classifications if c.priority == "urgent"]
    if urgent_items:
        lines.append("")  # blank line
        lines.append("**Urgent:**")
        for item in urgent_items[:5]:  # cap at 5 to keep the message tight
            lines.append(f"• {item.reason}")
        if len(urgent_items) > 5:
            lines.append(f"_+ {len(urgent_items) - 5} more urgent_")
    
    # Mention needs_response count without listing
    needs_resp_count = counts.get("needs_response", 0)
    if needs_resp_count > 0 and not urgent_items:
        lines.append(f"_{needs_resp_count} emails need a response — full list available on request._")
    
    if output.notes:
        lines.append(f"_{output.notes}_")
    
    return "\n".join(lines)
```

**Output contract:** under 500 chars in normal cases. Designed so Julius can post this directly without further synthesis when triage is the only meeseeks that ran. When triage is part of a `morning_briefing` swarm, Julius extracts the urgent items and the counts for a higher-level summary.

---

## Notes for OSS users

- **No API keys required.** This meeseeks needs only an LLM provider (already configured in meeseeks-core). Drop-in usable.
- **Caller is responsible for fetching emails.** This meeseeks classifies metadata; it doesn't pull from Gmail/IMAP/etc. Pair it with a separate fetcher (Julius integration, scheduled cron, manual paste).
- **Recommended cadence: 1-3 times daily.** Morning, midday, evening. More frequent runs are wasteful; less frequent loses the "what needs attention now" benefit.
- **`user_context` is the highest-leverage input.** Spend 5 minutes writing a good one. It's the difference between "generic triage" and "triage that knows what matters to you."
- **Confidence scores are advisory, not gatekeeping.** Don't auto-archive `ignore` items based on confidence alone. Use them to flag what to verify, not what to trust blindly.
- **Privacy posture:** body content never leaves the user's environment. Only metadata reaches the LLM. Users in regulated industries (healthcare, legal, finance) can verify this is consistent with their privacy requirements.

---

## Open questions

1. **Should we add a `domain_blocklist`/`domain_allowlist`** to user_context? Currently the model has to infer "this domain is marketing" from patterns. Explicit lists would be faster and more reliable but add input complexity.

2. **Is `is_reply` enough thread-context** or should we pass `thread_initiated_by_user: bool`? Distinguishing "reply to my outbound" vs. "reply in a thread someone else started" is meaningful for prioritization. Defer until real-use evidence shows the simpler signal is insufficient.

3. **Should the meeseeks return a suggested action** (archive / star / leave) per email? Currently it only classifies. Action suggestions add value but expand scope. Could be a separate `inbox_actions` meeseeks that consumes triage_inbox's output.

---

**End of spec.**

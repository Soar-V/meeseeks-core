# Meeseeks: draft_outreach

**Version:** 0.1
**Tier:** worker
**Toolkits:** none
**Destructive:** no
**Dynamic toolkits:** no
**Status:** draft

---

## Q1 — Single sentence description

Drafts outreach messages (email by default, optionally LinkedIn or SMS) to a specific recipient based on a stated objective and grounded findings, optionally adapted to the user's voice.

---

## Q2 — Input schema

```python
from typing import Literal, Optional
from pydantic import BaseModel, Field

class RecipientContext(BaseModel):
    name: str = Field(
        description="Recipient's name as known to the user. Used in greeting and references."
    )
    role: Optional[str] = Field(
        default=None,
        description="Title or role if known (e.g., 'Owner', 'CEO', 'Practice Manager'). Affects formality."
    )
    organization: Optional[str] = Field(
        default=None,
        description="Business or organization name. Skipped if generic personal outreach."
    )
    relationship: Literal["cold", "warm", "existing"] = Field(
        default="cold",
        description="cold = no prior contact. warm = mutual connection or prior brief touch. existing = ongoing relationship."
    )

class GroundingFact(BaseModel):
    fact: str = Field(
        max_length=200,
        description="One specific, verifiable thing about the recipient or their organization that the outreach can reference. E.g., 'Opened a second location in Plano in March 2026.'"
    )
    source: Optional[str] = Field(
        default=None,
        description="Where this fact came from. Optional but improves auditability."
    )

class Input(BaseModel):
    recipient: RecipientContext
    objective: str = Field(
        max_length=300,
        description="What the outreach should accomplish in plain language. E.g., 'Introduce my AI receptionist service and ask if they'd take a 15-min call to see if it fits their practice.' Be specific about the call-to-action."
    )
    grounding_facts: list[GroundingFact] = Field(
        default_factory=list,
        max_items=5,
        description="Specific facts that ground the outreach in something real. Strongly recommended for cold outreach. Each fact should be one the recipient would recognize as accurate."
    )
    channel: Literal["email", "linkedin", "sms"] = Field(
        default="email",
        description="Delivery channel. Each has different conventions for length, formatting, and tone."
    )
    sender_name: str = Field(
        description="Who is sending this. Used in sign-off."
    )
    sender_context: Optional[str] = Field(
        default=None,
        max_length=200,
        description="One-sentence framing of who the sender is. E.g., 'Solo founder of an AI agent business serving small medical practices.' Helps the meeseeks pick relevant framing."
    )
    n_variants: int = Field(
        default=1,
        ge=1,
        le=3,
        description="How many drafts to produce. 1 = single best draft. 2-3 = different angles for A/B testing."
    )
    constraints: Optional[str] = Field(
        default=None,
        max_length=300,
        description="Any explicit rules the user wants enforced. E.g., 'Under 80 words. No questions in the first sentence. Sign off with just my first name.'"
    )
```

**Field notes:**

- `recipient`, `objective`, and `sender_name` are the irreducible minimum. Everything else is optional but improves output significantly.
- `grounding_facts` is the single highest-leverage field for cold outreach quality. A draft with one specific fact ("saw you opened Plano in March") outperforms a draft without facts by a wide margin. Empty list is allowed but discouraged for cold outreach.
- `relationship` shifts tone defaults: cold = formal but specific, warm = referential ("Saw your post on..."), existing = familiar ("Following up on our last conversation").
- `n_variants` defaults to 1 because most outreach moments need one good draft. Opt into 2-3 when running an A/B test or when you want to choose between angles.
- `constraints` is the user's escape hatch for hard rules that override the meeseeks's defaults. Use it for length caps, forbidden phrases, formatting requirements.

---

## Q3 — Output schema (designed for synthesis)

```python
from typing import Optional
from pydantic import BaseModel, Field

class Variant(BaseModel):
    variant_id: str = Field(
        description="Short identifier for this variant within the spawn (e.g., 'a', 'b', 'c'). Used by Julius for reference."
    )
    angle: str = Field(
        max_length=100,
        description="One-phrase description of this variant's strategic angle. E.g., 'missed-revenue framing', 'staff-relief framing', 'curiosity-led opener'. Required even for n_variants=1."
    )
    subject: Optional[str] = Field(
        default=None,
        description="Subject line for email channel. None for LinkedIn/SMS."
    )
    body: str = Field(
        description="The draft itself. Plain text. Includes greeting and sign-off."
    )
    word_count: int = Field(
        ge=0,
        description="Approximate word count of body. For quick scanning."
    )
    grounded_in: list[str] = Field(
        default_factory=list,
        description="Which grounding_facts this variant references, by fact text. Empty if no facts referenced."
    )

class Output(BaseModel):
    variants: list[Variant] = Field(
        min_items=1,
        max_items=3,
        description="One Variant per requested draft. Length matches input.n_variants."
    )
    voice_guide_used: Optional[str] = Field(
        default=None,
        description="Name or path of the voice guide that shaped these drafts. None if no voice guide was provided. Used to surface 'generic tone warning' to the user."
    )
    channel: Literal["email", "linkedin", "sms"] = Field(
        description="Echoes the channel used. For Julius's format() to render appropriately."
    )
    notes: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Optional meta-observations: 'No grounding facts provided; drafts may feel generic.' or 'Constraint conflict: requested under 80 words but objective required more context.' Brief."
    )
```

**Synthesis notes:**

- `variants` always has at least one entry. The schema treats single-draft and multi-variant cases uniformly so Julius's synthesis logic doesn't branch.
- `angle` is required even for n_variants=1 because it forces the meeseeks to commit to one strategic framing rather than producing diluted everything-drafts.
- `grounded_in` lets the user (or Julius) audit whether the meeseeks actually used the facts provided. If grounding_facts were given but `grounded_in=[]` for all variants, the meeseeks ignored them — that's a signal worth surfacing.
- `voice_guide_used` is the field that powers the "generic tone" warning. None → user sees a note in `format()` that no voice guide was applied.

---

## Q4 — Toolkits required

**None.** Pure reasoning over the inputs and (optionally) the voice guide context bundle.

This meeseeks runs in subprocess (worker tier requires it for isolation), but doesn't make any external tool calls. Spawn cost is dominated by the LLM call itself.

---

## Q5 — Tier

**`worker`** (default model: Claude Sonnet, fallback: GPT-4o → DeepSeek).

**Reasoning:** Drafting good outreach requires:
- Voice mimicry (matching a provided style guide convincingly)
- Strategic framing (picking the right angle for the recipient and objective)
- Restraint (knowing what NOT to say — no AI tells, no clichés, no padding)
- Multi-source synthesis (objective + grounding facts + voice + constraints)

These together exceed thinker capabilities. A Haiku-tier draft will sound generic regardless of the voice guide; the model lacks the headroom to apply nuanced style transfer while also reasoning strategically about angle.

**Why not heavy:** Heavy is overkill for routine drafting. Reserved for tasks where Sonnet fails — strategic recommendations, complex synthesis across many sources, novel reasoning. Drafting is well-trodden ground for Sonnet.

**Cost calibration:**
- Single variant, no voice guide: ~$0.04–$0.06 per spawn.
- Single variant, with voice guide (~500 tokens): ~$0.06–$0.08 per spawn.
- 3 variants with voice guide: ~$0.12–$0.18 per spawn.

**Conservative estimate for approval-mode logic:** `estimated_cost_usd = 0.20` (covers max case, errs high so auto-approve is safe under $1 threshold).

---

## Q6 — System prompt

```
You are a draft_outreach meeseeks. Your only job is to produce one or
more outreach drafts (email, LinkedIn, or SMS) for a specific recipient
based on a stated objective.

You will receive: recipient details, an objective, optional grounding
facts, channel, sender info, requested variant count, and optional
constraints. You may also receive a voice guide via context bundle —
if present, every draft must adapt to that voice convincingly.

You must return: the requested number of variants, each with a stated
angle, subject (for email only), body, word count, and which grounding
facts (if any) were used.

Process:

1. Identify the strategic angle for each variant. If multiple variants
   are requested, each must take a meaningfully different angle (not
   minor wording variations). Common angles: problem-led, curiosity-led,
   social-proof-led, specific-fact-led, mutual-connection-led.

2. For cold outreach, anchor each draft in at least one grounding fact
   if any were provided. Reference the fact specifically and naturally —
   not "I noticed you recently..." (generic) but "Saw the Plano expansion
   in March..." (specific, immediate).

3. Match the voice guide if one is provided. Voice guide examples are
   gold — mimic the rhythm, the openings, the sign-offs, the length.
   If a phrase appears in the voice guide's "never say" list, do not
   use it under any circumstance.

4. Respect channel conventions:
   - Email: greeting + body + sign-off. Subject required.
     Default length: 60-120 words unless constraints say otherwise.
   - LinkedIn: shorter, more conversational. No subject. 40-80 words.
     Greeting may be omitted if the platform shows a name banner.
   - SMS: very short. 20-40 words. No greeting. Direct.

5. Apply constraints strictly. If a constraint conflicts with channel
   defaults or the objective's needs, follow the constraint and note
   the tradeoff in `notes`.

6. Self-check before returning: does this draft sound like a human wrote
   it? Or does it sound like an LLM? Specifically check for:
   - "I hope this email finds you well" → cliché, remove
   - "I wanted to reach out because..." → padding, remove
   - "I'd love to..." → fawning, remove unless voice guide allows it
   - "circle back / touch base / leverage / synergy" → corporate sludge
   - Multiple paragraphs of preamble before the actual ask → cut
   - Generic compliments without grounding → remove

Constraints:

- Do not invent facts about the recipient. Only reference grounding_facts
  provided. If no facts were provided, the draft must not pretend to
  know specifics about the recipient or their work.
- Do not produce variants that differ only in wording. If asked for
  multiple variants, each must commit to a different strategic angle.
- Do not pitch the sender's services or products in a hard-sell tone.
  The objective often involves introducing a service, but the draft
  should open conversation, not close a sale.
- Do not exceed channel length defaults unless constraints explicitly
  permit it. Long drafts are usually a sign of unclear thinking.
- Do not pad with closing pleasantries unless the voice guide includes
  them ("Looking forward to hearing back" / "Thanks in advance" / etc.
  are usually skippable).
- If no voice guide is provided, default to a tone that is direct,
  specific, and free of LLM tells. Note the absence in the output.

Failure handling:

- If the objective is too vague to draft (e.g., "say hi to John"),
  return failure with reason="objective_too_vague" and partial containing
  what you would need to know.
- If grounding_facts contradict each other or the objective, follow
  the objective and note the conflict in `notes`.
- If a constraint cannot be satisfied alongside the objective, prefer
  the constraint, note the tradeoff.
- If the voice guide is malformed or unparseable, fall back to generic
  tone and note this in the output.

Format:

Return only the structured Output schema. No commentary, no
"here are your drafts" preamble. The variants list must contain
exactly the requested number of variants.
```

**Word count: ~490 words.** Within the 500-word budget per playbook §5.4.

---

## Q7 — Context bundle

**Optional voice guide.** This is the meeseeks that introduces the voice-guide pattern.

**Mechanism:**

1. **Default voice guide via Julius config.** Julius's config file specifies a default voice guide that applies to every `draft_outreach` spawn unless overridden:

```yaml
# julius.config.yaml
default_voice_guides:
  draft_outreach: ./voice/alex_voice.md
```

When Julius spawns `draft_outreach`, it auto-attaches the configured voice guide to the context bundle. User does nothing per-spawn.

2. **Spawn-time override.** Caller can attach a different voice guide at spawn time, which overrides the default:

```python
summon(
    "draft_outreach",
    inputs=...,
    context_bundle=[ContextSource.file("voice/colleague_voice.md")]
)
```

3. **No voice guide.** If no default is configured AND no override is supplied, the meeseeks runs without a voice guide, sets `voice_guide_used=None`, and uses the generic-but-clean tone described in the system prompt.

**Voice guide format:**

A markdown file. No required structure, but the most useful guides include:

- 2-4 example outreach drafts the user has actually sent (gold standard)
- A "never say" list of phrases the user avoids
- Sign-off conventions
- Length preferences
- Tone guidance ("direct, slightly informal, no corporate jargon")
- Optional: industry or domain context

The meeseeks reads the voice guide as plain text and infers patterns. Structure is for the user's clarity, not the meeseeks's parsing.

**Voice guide token budget:** ~500-1500 tokens recommended. Longer guides bloat spawn cost without proportional quality gains. If a guide is >2000 tokens, the meeseeks reads it but the cost calibration above no longer applies.

---

## Q8 — Failure modes

| # | Failure mode | Detection | Structured response |
|---|---|---|---|
| 1 | Objective too vague to draft | Model can't identify a clear ask, intent, or call-to-action | `status="failure"`, `reason="objective_too_vague"`, `partial` lists what specifics would help. |
| 2 | Grounding facts contradict objective | E.g., objective is "thank them for partnering" but a fact says "no prior interaction" | `status="success"` with `notes` flagging the conflict; meeseeks proceeds with the objective. |
| 3 | Voice guide malformed/unparseable | Provided but cannot be used | Returns drafts with `voice_guide_used=None` and `notes` explaining. Status `success`. |
| 4 | Constraint cannot be satisfied | E.g., "under 30 words" + "include 3 facts + sign-off" is impossible | Drafts respect constraint as priority, `notes` explains tradeoff. Status `success`. |
| 5 | Schema validation failure | Returned variants list wrong length, or required fields missing | Framework validate-and-retry per §4.4. Returns `failure` after two attempts. |
| 6 | Variants insufficiently differentiated | Internal sanity check (n_variants > 1): variants share >70% body content or have same `angle` value | `status="failure"`, `reason="variants_not_differentiated"`, `partial` includes the duplicates for review. |
| 7 | Hallucination guard tripped | Internal check: variant body references specifics not in grounding_facts and not derivable from recipient/sender context | `status="failure"`, `reason="hallucination_guard"`, `partial` flags suspect content. |
| 8 | Voice mimicry failed obviously | Voice guide provided but draft contains phrases from the "never say" list (if explicit) | `status="failure"`, `reason="voice_violation"`, `partial` shows the violating draft. |

**Failure modes #6, #7, and #8 are the integrity guards** specific to this meeseeks. Without them, the meeseeks would silently fail in ways that erode trust:
- #6 protects against "3 variants" actually being one draft with synonym swaps.
- #7 protects against the model inventing recipient details that sound plausible but aren't grounded.
- #8 protects against the most embarrassing failure mode: the voice guide says "never use 'circle back'" and the draft says "let's circle back next week."

---

## format() method

```python
def format(self, output: Output) -> str:
    """Render Output as a Discord-friendly summary for Julius's synthesis."""
    if not output.variants:
        return "**Outreach drafts:** none produced."
    
    lines = []
    
    # Header with channel and voice attribution
    voice_note = ""
    if output.voice_guide_used:
        voice_note = f" · voice: `{output.voice_guide_used}`"
    elif output.voice_guide_used is None:
        voice_note = " · ⚠️ no voice guide (generic tone)"
    
    lines.append(f"**Outreach draft ({output.channel}){voice_note}**")
    
    # For single variant: show the draft directly
    if len(output.variants) == 1:
        v = output.variants[0]
        lines.append(f"_Angle: {v.angle}_")
        if v.subject:
            lines.append(f"**Subject:** {v.subject}")
        lines.append("")
        lines.append(v.body)
        lines.append("")
        lines.append(f"_{v.word_count} words_")
    
    # For multiple variants: list with angles, body in collapsible/code block
    else:
        lines.append(f"_{len(output.variants)} variants produced_")
        for v in output.variants:
            lines.append("")
            lines.append(f"**Variant {v.variant_id.upper()}** — _{v.angle}_")
            if v.subject:
                lines.append(f"Subject: {v.subject}")
            lines.append(f"```\n{v.body}\n```")
            lines.append(f"_{v.word_count} words_")
    
    if output.notes:
        lines.append("")
        lines.append(f"_{output.notes}_")
    
    return "\n".join(lines)
```

**Output contract:** single-variant drafts are shown inline (clean, copyable). Multi-variant drafts use code blocks for separation and easy copying. The voice-guide attribution is always shown — either the path used or a clear warning that none was applied.

---

## Notes for OSS users

- **Voice guide is the highest-leverage optional input.** Spend 30 minutes writing one. Format is your choice — the meeseeks reads markdown freely.
- **A great voice guide includes 2-3 actual emails you've sent.** Examples beat instructions. The meeseeks pattern-matches better than rule-follows.
- **Different voice guides for different contexts.** You can configure per-context defaults if your voice differs (e.g., `voice/sales_voice.md` vs `voice/personal_voice.md`) and pick at spawn time.
- **Grounding facts matter most for cold outreach.** Without facts, even a perfect voice guide produces forgettable drafts. Pair `draft_outreach` with `research_prospect` for the strongest results.
- **The "no AI tells" guarantee is best-effort, not absolute.** Models drift. Review every draft before sending. The meeseeks reduces the volume of obviously-AI text dramatically but doesn't eliminate it.
- **Channel choice matters more than people think.** Email defaults assume professional B2B. LinkedIn defaults to peer-to-peer. SMS defaults to brief and direct. Pick the channel that matches the relationship, not just the platform you have access to.
- **For A/B testing:** request 2-3 variants with deliberately different angles (Curie principle). The `angle` field is what makes A/B results meaningful — you're testing strategic framings, not wording variations.

---

## Open questions

1. **Should the meeseeks accept a "previous attempts" input** — e.g., "this is the third email in a sequence, here are the first two"? Useful for follow-ups. Defer until real use shows demand; could be a separate `draft_followup` meeseeks.

2. **Should the voice guide be parsed into a structured schema** rather than passed as raw markdown? Would enable programmatic checks ("does this draft match the voice guide's length rules?"). Adds upfront cost; defer.

3. **Should there be a "review against voice guide" pass** as a separate meeseeks? Currently the voice check is internal to draft_outreach. A separate `voice_review` meeseeks would let users audit existing drafts against a guide. Defer to library v2.

4. **Should `n_variants` be allowed >3?** Hard cap at 3 in v1 keeps cost bounded and forces strategic differentiation (more than 3 truly distinct angles is rare). Open to revisiting if real use shows demand.

---

**End of spec.**

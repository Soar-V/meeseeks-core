# Meeseeks: prep_for_meeting

**Version:** 0.1
**Tier:** worker
**Toolkits:** `firecrawl`, `http_fetch` (only when `research_attendees=True`)
**Destructive:** no
**Dynamic toolkits:** yes (toolkits attached only when research is enabled)
**Status:** draft

---

## Q1 — Single sentence description

Produces a focused prep brief for an upcoming meeting, tailored to the meeting type, optionally enriched with web research on external attendees.

---

## Q2 — Input schema

```python
from typing import Literal, Optional
from pydantic import BaseModel, Field

class Attendee(BaseModel):
    name: str = Field(
        description="Attendee's name as known to the user."
    )
    email: Optional[str] = Field(
        default=None,
        description="Email if known. Used for domain-based 'internal vs external' inference."
    )
    organization: Optional[str] = Field(
        default=None,
        description="Organization or company name if known."
    )
    role: Optional[str] = Field(
        default=None,
        description="Role or title if known. Affects prep emphasis."
    )
    is_external: Optional[bool] = Field(
        default=None,
        description="True if this attendee is external to the user's organization. None = caller didn't specify; meeseeks infers from email domain if possible."
    )

class Input(BaseModel):
    title: str = Field(
        description="Meeting title from the calendar invite. May be vague — that's fine."
    )
    meeting_type: Literal[
        "sales_call",
        "internal_review",
        "interview",
        "client_check_in",
        "external_intro",
        "team_sync",
        "vendor_pitch",
        "other"
    ] = Field(
        description="The meeting's nature. Drives what the prep emphasizes."
    )
    start_time: str = Field(
        description="ISO 8601 datetime when the meeting starts. Used to compute 'time until meeting' and date references."
    )
    duration_minutes: Optional[int] = Field(
        default=None,
        ge=5,
        description="Meeting length. Affects depth of prep — a 15-min meeting needs different prep than a 90-min one."
    )
    attendees: list[Attendee] = Field(
        default_factory=list,
        max_items=20,
        description="Known attendees. May be empty if not provided (e.g., recurring meeting where attendees are implicit)."
    )
    description: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Calendar event description, agenda, or any text that came with the invite. Often the highest-signal field when present."
    )
    meeting_url: Optional[str] = Field(
        default=None,
        description="Zoom, Meet, Teams, or other meeting URL. Not used for content; useful for output reference."
    )
    user_context: Optional[str] = Field(
        default=None,
        max_length=500,
        description="What the user wants to get out of this meeting. E.g., 'I want to understand if their pricing fits our budget' or 'I'm trying to determine if this candidate has the systems experience we need.' Drives what the prep emphasizes."
    )
    prior_context: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Notes, prior emails, or summary from past meetings with the same attendees. Free-form text. Skip if no prior context."
    )
    research_attendees: bool = Field(
        default=False,
        description="If True, the meeseeks will use firecrawl to research external attendees. Adds ~30-60s and ~$0.05-$0.15 to spawn. Default False to keep cheap meetings cheap."
    )
    current_time: str = Field(
        description="ISO 8601 timestamp the meeseeks should treat as 'now'."
    )
```

**Field notes:**

- All input fields beyond `title`, `meeting_type`, `start_time`, and `current_time` are optional. The meeseeks adapts to what's provided.
- `meeting_type` is required and explicit (no auto-detection). Meeting titles lie ("Quick chat" might be a layoff conversation or a coffee catch-up). Forcing the caller to declare type produces reliable output.
- `description` is the single highest-signal optional field when present. Many calendar invites carry agendas in the description; the meeseeks extracts heavily from this.
- `user_context` is what makes the prep *yours* rather than generic. "I want X" framing produces prep that helps you achieve X. Without it, the prep is a defensible-but-generic agenda walkthrough.
- `prior_context` lets users paste relevant emails or notes without forcing a structured schema. Free-form is fine — the meeseeks reads as text.
- `research_attendees` defaults to False (cost discipline). Enable when meeting attendees are external and unknown; skip for internal or familiar meetings.

---

## Q3 — Output schema (designed for synthesis)

```python
from typing import Optional
from pydantic import BaseModel, Field

class TalkingPoint(BaseModel):
    point: str = Field(
        max_length=200,
        description="A specific thing to bring up, ask, or clarify. Concrete, not generic."
    )
    why: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Brief rationale for why this point matters in this meeting. Optional but valuable."
    )
    priority: Literal["must_cover", "should_cover", "if_time"] = Field(
        description="must_cover = the meeting fails if this isn't addressed. should_cover = important but not blocking. if_time = nice-to-have."
    )

class Question(BaseModel):
    question: str = Field(
        max_length=200,
        description="A specific question to ask, phrased the way the user would actually say it."
    )
    target_attendee: Optional[str] = Field(
        default=None,
        description="Who to direct the question to, if specific. None for open questions."
    )
    purpose: Optional[str] = Field(
        default=None,
        max_length=150,
        description="What the user is trying to learn from the answer. Brief."
    )

class AttendeeBrief(BaseModel):
    name: str
    role_summary: Optional[str] = Field(
        default=None,
        max_length=200,
        description="One-sentence summary of who this person is and what they likely care about. Empty if not researched and no info available."
    )
    research_findings: list[str] = Field(
        default_factory=list,
        max_items=3,
        description="Up to 3 specific findings from web research, if research_attendees was True. Each grounded in a source. Empty if research was off or yielded nothing."
    )
    research_source_urls: list[str] = Field(
        default_factory=list,
        description="URLs that informed research_findings. Same length as findings or empty."
    )

class RiskOrFlag(BaseModel):
    flag: str = Field(
        max_length=200,
        description="Something that might go sideways or need attention. Concrete."
    )
    severity: Literal["watch", "concern", "red_flag"] = Field(
        description="watch = minor awareness. concern = address proactively. red_flag = consider whether to take the meeting / change format."
    )

class Output(BaseModel):
    title: str = Field(description="Echoes input title.")
    meeting_type: str = Field(description="Echoes input meeting_type.")
    starts_in_minutes: int = Field(
        description="Computed from start_time and current_time. Negative if meeting already started/passed."
    )
    headline: str = Field(
        max_length=300,
        description="One- to two-sentence orientation. What this meeting is, what's at stake. The first thing the user reads."
    )
    objective: Optional[str] = Field(
        default=None,
        max_length=300,
        description="What success looks like in this meeting, derived from user_context. None if user didn't provide context."
    )
    talking_points: list[TalkingPoint] = Field(
        default_factory=list,
        max_items=8,
        description="Things the user should bring up. Ordered by priority (must_cover first), then by importance."
    )
    questions_to_ask: list[Question] = Field(
        default_factory=list,
        max_items=6,
        description="Questions that advance user_context's goal. Ordered by importance."
    )
    attendee_briefs: list[AttendeeBrief] = Field(
        default_factory=list,
        description="One brief per known attendee. Empty list if attendees weren't provided."
    )
    risks_or_flags: list[RiskOrFlag] = Field(
        default_factory=list,
        max_items=5,
        description="Things to watch out for. Empty if nothing notable."
    )
    notes: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Optional meta-observations: 'Calendar description was sparse; prep is based mostly on title and meeting type.' Brief."
    )
```

**Synthesis notes:**

- `headline` is the first thing the user reads — it should be readable on a phone notification at 8:55am for a 9:00am meeting.
- `objective` only populates when `user_context` was provided. Otherwise the prep stays neutral about "what success looks like" — the user already knows.
- `talking_points` are *what to say*; `questions_to_ask` are *what to ask*. Mutually distinct on purpose.
- `attendee_briefs` always has one entry per known attendee, even if research was off. The `role_summary` field uses provided role/org data; `research_findings` is empty when research wasn't run.
- `risks_or_flags` is intentionally limited — five max — to prevent paranoia briefs that flag every possible thing. The meeseeks only surfaces flags worth surfacing.

---

## Q4 — Toolkits required

**`firecrawl` and `http_fetch` — only when `research_attendees=True`.**

This meeseeks uses **dynamic toolkits** (per playbook §Q4 advanced pattern). When `research_attendees=False`, no toolkits attach — the meeseeks runs as pure reasoning over inputs. When `research_attendees=True`, the framework attaches `firecrawl` and `http_fetch` for the duration of the spawn.

**Justification for dynamic toolkits:** Most meetings are internal or with known attendees, where research is wasteful. Most cold/sales meetings benefit from research. Tying toolkit attachment to the boolean lets the same meeseeks serve both cases without a second meeseeks variant or always-on toolkit cost.

**Tools used (when research enabled):**
- `firecrawl.scrape` — extract content from attendee LinkedIn profiles, company sites, recent press.
- `http_fetch` — fallback for simple static pages.

**Not included:**
- ❌ Search tools — for meetings, the user typically knows the attendee's organization name. Constructing candidate URLs from name + organization works well enough. If discovery becomes a bottleneck in real use, add search later.
- ❌ Calendar API integration — the meeseeks consumes calendar data; it doesn't fetch from Google Calendar / Outlook. Caller (Julius or a workflow) handles fetching.

---

## Q5 — Tier

**`worker`** (default model: Claude Sonnet, fallback: GPT-4o → DeepSeek).

**Reasoning:** The job involves:
- Type-aware reasoning (different meeting types require different prep emphases)
- Synthesis across multiple inputs (description + prior_context + attendees + user_context)
- Generating specific, non-generic talking points and questions
- Optional multi-source research integration

This exceeds thinker capabilities. A Haiku-tier prep brief would produce generic agenda items ("Discuss timeline," "Review action items") rather than specific ones grounded in the actual context.

**Why not heavy:** Meeting prep is well-trodden ground for Sonnet. Heavy adds cost without proportional quality gains for prep work specifically.

**Cost calibration:**
- No research, sparse inputs (just title + type + time): ~$0.04–$0.06 per spawn.
- No research, full context (description + prior_context + attendees): ~$0.06–$0.10 per spawn.
- With research (3 attendees, ~5 firecrawl calls): ~$0.10–$0.18 per spawn.

**Conservative estimate for approval-mode logic:**
- Without research: `estimated_cost_usd = 0.10`
- With research: `estimated_cost_usd = 0.25`

(Estimate provided to Julius adapts based on `research_attendees` value at spawn time.)

---

## Q6 — System prompt

```
You are a prep_for_meeting meeseeks. Your only job is to produce a
focused prep brief for one upcoming meeting, tailored to the meeting
type, using the inputs provided.

You will receive: meeting metadata (title, type, time, duration),
optional attendees, optional description and prior context, optional
user_context, and a flag for whether to research external attendees.

You must return: a structured Output with headline, optional objective,
talking points, questions to ask, attendee briefs, optional risks/flags,
and notes.

Meeting types and their emphases:

SALES_CALL — pitching or selling to an external prospect.
  Emphasize: value props relevant to attendee's role, anticipated
  objections + responses, pricing/process talking points only if
  user_context indicates readiness, the specific ask. Questions
  emphasize qualification (budget, authority, need, timeline).

INTERNAL_REVIEW — review meeting with colleagues or leadership.
  Emphasize: status updates worth surfacing, decisions needed,
  questions for leadership. Avoid pitching tone.

INTERVIEW — interviewing a candidate (or being interviewed).
  Emphasize: questions to assess fit, areas to probe, red flags
  from background. Questions are central; talking points minimal.

CLIENT_CHECK_IN — recurring with existing client.
  Emphasize: continuity from prior_context if provided, status of
  ongoing work, questions about evolving needs, opportunities to
  expand. Less ceremony, more substance.

EXTERNAL_INTRO — first meeting with an external party (non-sales).
  Emphasize: rapport-building openings, mutual context-setting,
  exploratory questions. Avoid hard asks.

TEAM_SYNC — recurring internal team meeting.
  Emphasize: status to share, blockers to surface, decisions needed.
  Brief is short; team syncs need orientation, not deep prep.

VENDOR_PITCH — vendor pitching to the user.
  Emphasize: questions that test fit and qualify the vendor,
  comparison criteria, what to look for in the demo, red flags.

OTHER — type unclear or doesn't fit above.
  Produce a generic but useful prep based on title and any context.

Process:

1. Read all inputs first. Establish: meeting type, who's there,
   what's at stake, what user wants out of it.

2. If research_attendees=True, identify external attendees (via
   is_external flag, or by inferring from email domain). For each:
   - Construct a candidate URL (org name + name → likely LinkedIn
     or company bio page).
   - Use firecrawl.scrape to fetch and extract relevant content.
   - Capture up to 3 specific findings per attendee. Each finding
     must have a source URL.
   - Skip research for any attendee where no plausible URL is found.

3. Generate the headline. One- to two-sentence orientation that
   captures what this meeting is and why it matters. Concrete.

4. Generate the objective if user_context was provided. State what
   success looks like in this specific meeting.

5. Generate talking_points (max 8). Each must:
   - Be specific to this meeting, not generic ("Build rapport" → no)
   - Have priority set honestly (most are should_cover; reserve
     must_cover for the 1-2 things the meeting fails without)
   - Include why if the rationale isn't obvious

6. Generate questions_to_ask (max 6). Each must:
   - Be phrased the way the user would actually ask it (not formal
     interview-script style)
   - Tie to advancing user_context's goal when context was provided
   - Specify target_attendee only when the question is for a specific
     person; leave None for open questions

7. Generate attendee_briefs. One per known attendee. role_summary
   uses whatever's provided; research_findings populated only if
   research was run and yielded specifics.

8. Generate risks_or_flags only when warranted. Examples of legitimate
   flags:
   - Severity "concern": Tight schedule (15 min for 5 attendees on
     a complex topic), recent public news suggesting attendee may
     be in a difficult moment.
   - Severity "red_flag": The meeting setup itself is problematic
     (sales call mistakenly scheduled as a check-in, attendee list
     suggests a layoff conversation).
   - Do not invent flags. If nothing is notable, return an empty list.

Constraints:

- Do not invent attendee details when research_attendees=False.
  The role_summary uses only provided role/org data.
- Do not invent meeting context not present in inputs. If description
  is sparse and user_context is missing, the prep stays appropriately
  generic — note this in `notes`.
- Do not produce talking_points or questions that are clichés or
  apply to any meeting ("Confirm action items," "Set next steps").
  These are useless. If the only specific points you can think of
  are clichés, return fewer points or empty lists.
- Do not over-flag. risks_or_flags are for genuine concerns. A
  default meeting with full context has zero flags.
- Do not pad the brief. A 15-min team sync needs a 3-talking-point
  prep, not 8.

Failure handling:

- If research_attendees=True but firecrawl is unavailable, return
  success with research_findings empty across all attendees and
  notes flagging the tool failure. Do not fail the whole meeseeks.
- If inputs are extremely sparse (just title + type + time, nothing
  else), return success with brief, neutral output and notes
  flagging the gap.
- If meeting_type is "other" and inputs offer no clue what kind of
  meeting it is, generate a basic agenda-walk prep with notes
  recommending the user clarify type.

Format:

Return only the structured Output schema. No commentary.
```

**Word count: ~620 words.** Slightly over the 500-word target due to the meeting-type taxonomy. Acceptable given the taxonomy is structured (one paragraph per type) and the structure earns its keep — without it, type-aware prep doesn't work.

---

## Q7 — Context bundle

**None required.**

The meeseeks operates from `Input` only. The optional `description`, `prior_context`, and `user_context` fields carry any reference material directly in the input.

**Note for OSS users:** unlike `draft_outreach`, this meeseeks doesn't benefit from a persistent voice guide. Each meeting is its own context. If recurring meetings have stable context (e.g., always-the-same team sync), pass it via `prior_context` per spawn rather than configuring a persistent file.

---

## Q8 — Failure modes

| # | Failure mode | Detection | Structured response |
|---|---|---|---|
| 1 | start_time in the past | Computed `starts_in_minutes < -60` | Return success but `notes` flags "meeting may have already happened — prep is retrospective." User decides whether output is useful. |
| 2 | research_attendees=True but firecrawl unavailable | Tool errors persistently | Return success with empty research_findings across attendees, `notes` flagging "research requested but firecrawl unavailable." Don't fail the whole meeseeks. |
| 3 | Schema validation failure | Output malformed | Framework validate-and-retry per §4.4. Returns failure after two attempts. |
| 4 | Talking points or questions are clichéd | Internal check: matches a generic-content blocklist ("confirm action items", "build rapport", "set next steps", etc.) | Soft check — flagged items get rewritten on retry, only fails if all attempts produce only clichés. Returns failure with `reason="generic_content"`. |
| 5 | Hallucination guard tripped | Internal check: attendee research_findings cite URLs that weren't actually fetched | `status="failure"`, `reason="hallucination_guard"`, `partial` includes the suspect attendee brief. |
| 6 | No talking points AND no questions generated for a non-team-sync | All three lists empty for a meeting type that should have substance | `status="failure"`, `reason="empty_brief"`, retry once with stronger prompt. |
| 7 | Timeout | Spawn exceeds 120s (worker default; 180s with research) | `status="timeout"`, `partial` contains whatever was assembled. |

**Failure mode #4 is the anti-cliché guard.** Meeting prep is the meeseeks most prone to "useful-sounding generic output." Without active guarding, the meeseeks would consistently produce "Confirm action items" and "Build rapport" as filler. Better to return a shorter, sharper brief than a long, useless one.

**Failure mode #5 is the research integrity guard.** When research_attendees=True, every research_findings entry must have a source URL that was actually fetched during this run. Hallucinated findings about real people are the worst possible failure for a prep meeseeks.

---

## format() method

```python
def format(self, output: Output) -> str:
    """Render Output as a Discord-friendly summary for Julius's synthesis."""
    lines = []
    
    # Header with countdown
    if output.starts_in_minutes < 0:
        time_str = f"⚠️ Started {abs(output.starts_in_minutes)} min ago"
    elif output.starts_in_minutes < 60:
        time_str = f"in {output.starts_in_minutes} min"
    else:
        hours = output.starts_in_minutes // 60
        mins = output.starts_in_minutes % 60
        time_str = f"in {hours}h {mins}m" if mins else f"in {hours}h"
    
    lines.append(f"**{output.title}** _({output.meeting_type}, {time_str})_")
    lines.append("")
    lines.append(output.headline)
    
    if output.objective:
        lines.append("")
        lines.append(f"**Goal:** {output.objective}")
    
    # Must-cover talking points get top billing
    must_cover = [tp for tp in output.talking_points if tp.priority == "must_cover"]
    other_points = [tp for tp in output.talking_points if tp.priority != "must_cover"]
    
    if must_cover:
        lines.append("")
        lines.append("**Must cover:**")
        for tp in must_cover:
            lines.append(f"• {tp.point}")
    
    if other_points:
        lines.append("")
        lines.append("**Talking points:**")
        for tp in other_points[:4]:
            lines.append(f"• {tp.point}")
        if len(other_points) > 4:
            lines.append(f"_+ {len(other_points) - 4} more_")
    
    if output.questions_to_ask:
        lines.append("")
        lines.append("**Ask:**")
        for q in output.questions_to_ask[:4]:
            target = f" _(→ {q.target_attendee})_" if q.target_attendee else ""
            lines.append(f"• {q.question}{target}")
        if len(output.questions_to_ask) > 4:
            lines.append(f"_+ {len(output.questions_to_ask) - 4} more questions_")
    
    # Attendees with research findings (only show those with findings)
    researched = [a for a in output.attendee_briefs if a.research_findings]
    if researched:
        lines.append("")
        lines.append("**Attendees:**")
        for a in researched:
            top_finding = a.research_findings[0]
            lines.append(f"• **{a.name}** — {top_finding}")
    
    # Risks/flags surfaced loudly when present
    red_flags = [r for r in output.risks_or_flags if r.severity == "red_flag"]
    concerns = [r for r in output.risks_or_flags if r.severity == "concern"]
    
    if red_flags:
        lines.append("")
        for flag in red_flags:
            lines.append(f"🚩 {flag.flag}")
    
    if concerns:
        for concern in concerns:
            lines.append(f"⚠️ {concern.flag}")
    
    if output.notes:
        lines.append("")
        lines.append(f"_{output.notes}_")
    
    return "\n".join(lines)
```

**Output contract:** under 1000 chars in typical cases. The countdown in the header is the most useful field for a prep brief — when the user reads this depends on when the meeting is. Red flags and concerns are surfaced prominently when present; absent when not. The format gracefully degrades for sparse meetings (team syncs with minimal prep) without producing empty sections.

---

## Notes for OSS users

- **`meeting_type` is the highest-leverage required field.** Different types produce dramatically different briefs. Picking the right type matters more than filling out optional fields.
- **`user_context` is the highest-leverage optional field.** A 1-2 sentence "what I want from this meeting" produces sharply better prep than the default neutral framing.
- **`description` is the highest-leverage optional context field.** Many calendar invites carry agendas in their description. The meeseeks extracts heavily from this when present.
- **Research is opt-in to control cost.** Default `research_attendees=False` keeps the meeseeks cheap for routine internal meetings. Enable for cold/external/sales meetings where attendee context matters.
- **Pair with `research_prospect` for sales calls.** For high-stakes sales calls, run `research_prospect` on the prospect's organization first, then feed the brief into `prep_for_meeting` via `prior_context`. Two-step but produces much sharper prep than research_attendees=True alone.
- **Recurring meetings: keep `prior_context` updated.** For weekly check-ins, paste the previous meeting's notes or summary into `prior_context`. The meeseeks uses this for continuity rather than treating each meeting as a first encounter.
- **Don't trust attendee research blindly.** Web research can be wrong, outdated, or about a different person with the same name. The `research_source_urls` field is provided so the user can verify findings before relying on them.

---

## Open questions

1. **Should the meeseeks accept multiple meetings as input** (e.g., "prep me for the next 3 meetings today")? Currently one meeting per spawn. Batching could reduce spawn overhead but multiplies failure modes. Defer; let Julius run multiple spawns in parallel if needed.

2. **Should there be a "post-meeting follow-up" output** generated alongside prep? E.g., "After this meeting, here's what to do." Useful but expands scope. Defer to a `post_meeting_actions` meeseeks if real demand emerges.

3. **Should research_attendees be inferred from meeting_type** (e.g., always research for sales_call)? Tempting but fragile — internal sales meetings exist. Better to keep it explicit and let callers (Julius) layer that logic.

4. **Should attendee research persist as findings** for reuse in subsequent meetings with the same person? Currently every spawn researches fresh. Caching would reduce cost but adds complexity. Defer; users can paste prior findings via `prior_context`.

---

**End of spec.**

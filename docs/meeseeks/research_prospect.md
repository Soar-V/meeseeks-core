# Meeseeks: research_prospect

**Version:** 0.1
**Tier:** worker
**Toolkits:** `firecrawl`, `http_fetch`
**Destructive:** no
**Dynamic toolkits:** no
**Status:** draft

---

## Q1 — Single sentence description

Researches a single business and returns recent activity, contact information, and conversation hooks suitable for outreach or context-gathering.

---

## Q2 — Input schema

```python
from typing import Literal, Optional
from pydantic import BaseModel, Field

class Input(BaseModel):
    business_name: str = Field(
        description="Exact name of the business to research, as known to the user"
    )
    business_type: str = Field(
        description="Industry or category to scope the search (e.g., 'plastic surgery practice', 'HVAC contractor', 'dental clinic'). Used to disambiguate common names."
    )
    location: Optional[str] = Field(
        default=None,
        description="City, region, or state if known. Improves search precision for businesses with common names."
    )
    lookback_days: int = Field(
        default=90,
        ge=1,
        le=365,
        description="Window for 'recent' activity. Defaults to 90 days, which catches quarterly news cycles."
    )
    depth: Literal["quick", "thorough"] = Field(
        default="quick",
        description="quick = ~3 sources, ~30 sec, ~$0.05. thorough = ~8 sources, ~90 sec, ~$0.15."
    )
    known_url: Optional[str] = Field(
        default=None,
        description="Business's website if known. Skips a search step and improves accuracy."
    )
```

**Field notes:**

- `business_name` and `business_type` are required because business identity needs both to disambiguate. "Smart" alone is ambiguous; "Dr. Smart, plastic surgery" resolves cleanly.
- `location` is optional but strongly recommended. Without it, common names produce noisy results.
- `lookback_days` defaults to 90 because that catches quarterly press cycles, magazine features, and seasonal announcements. Tighten to 30 for active-news windows; widen to 180 for slower-moving B2B contexts.
- `depth` is the cost/quality dial. The meeseeks honors it strictly — `quick` does not silently expand into `thorough`.
- `known_url` is a hint, not a constraint. The meeseeks may still discover other relevant URLs.

---

## Q3 — Output schema (designed for synthesis)

```python
from typing import Optional
from pydantic import BaseModel, Field

class Activity(BaseModel):
    summary: str = Field(
        description="One-sentence description of what happened. Past tense. No quotes from source."
    )
    source_url: str = Field(
        description="Direct URL to the source. Required — every claim is attributable."
    )
    date: Optional[str] = Field(
        default=None,
        description="ISO 8601 date if found in source, else None. Do not infer dates."
    )
    confidence: Literal["high", "medium", "low"] = Field(
        description="high = direct primary source. medium = secondary mention. low = inferred or aggregator-derived."
    )

class ContactInfo(BaseModel):
    website: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    primary_contact_name: Optional[str] = None
    primary_contact_role: Optional[str] = None

class Output(BaseModel):
    business_name: str = Field(
        description="The business as found. May differ slightly from input if a more canonical form exists."
    )
    found: bool = Field(
        description="True if the business was successfully identified and at least one piece of information was retrieved."
    )
    recent_activity: list[Activity] = Field(
        default_factory=list,
        description="Activity within the lookback window. May be empty if found=True but nothing recent. Ordered most-recent first."
    )
    contact_info: Optional[ContactInfo] = Field(
        default=None,
        description="None if no contact info could be verified. Partial fields are fine — populate what's known."
    )
    opening_hooks: list[str] = Field(
        default_factory=list,
        max_items=3,
        description="Up to 3 conversation starters grounded in the recent activity. Each hook references a specific finding, not generic praise."
    )
    notes: Optional[str] = Field(
        default=None,
        description="Free-form notes about data quality, gaps, or anything Julius should surface to the user. Brief — under 200 chars."
    )
    sources_consulted: int = Field(
        ge=0,
        description="How many URLs were actually fetched. For cost/effort visibility."
    )
```

**Synthesis notes:**

- When 3+ `research_prospect` meeseeks run in a swarm, Julius synthesizes them into a single briefing. Each `Output` must therefore be **independently complete** — no field assumes context from sibling outputs.
- `recent_activity` is a list, not prose, so Julius can sort, filter, or interleave findings across multiple businesses.
- `opening_hooks` are explicitly capped at 3 to prevent the model from padding. Quality over quantity.
- `confidence` on each activity lets Julius surface uncertainty in the synthesized output ("Per a primary source, Anigian opened a second location" vs "An aggregator suggests Setty was featured in D Magazine").
- `found=False` is a valid success — the meeseeks completed its job and concluded the business couldn't be reliably identified. This is different from `status="failure"` (an execution problem).

---

## Q4 — Toolkits required

**`firecrawl`** — Primary tool for reading web pages.
- Used for: extracting clean content from URLs discovered during research.
- Endpoint: `/scrape` for general pages, `/extract` when targeting specific structured data (contact info, dates).
- Justification: Firecrawl handles JavaScript-rendered pages, anti-bot challenges, and produces clean markdown that the model can reason over without HTML noise.

**`http_fetch`** — Fallback for direct HTTP requests.
- Used for: simple static pages where Firecrawl is overkill, sites that block Firecrawl, or when checking if a URL is reachable.
- Justification: Cost-free fallback. Many small-business sites are static HTML and don't need a scraping service.

**No search tool in v1.** This is a deliberate limitation. The meeseeks works best when given a `known_url` or when the business name + type + location is specific enough that a search step isn't required for discovery. Future v2 may add `brave_search` or equivalent if real use shows discovery is the bottleneck.

**Not included and why:**
- ❌ Email finders (Hunter.io, Apollo): contact discovery is a separate concern; belongs in a future `find_contact` meeseeks.
- ❌ Social media scrapers: too brittle, low signal-to-noise.
- ❌ Google Places API: useful for verified contact info, but adds vendor dependency. Defer until real use shows contact info quality is poor.
- ❌ LinkedIn lookup: legally murky, technically fragile. Out of scope.

---

## Q5 — Tier

**`worker`** (default model: Claude Sonnet, fallback: GPT-4o → DeepSeek).

**Reasoning:** Multi-step reasoning over external data with user-facing tone. Specifically:
- Reads multiple URLs and synthesizes findings
- Filters by date and relevance
- Generates conversation hooks that require nuance and grounding
- Outputs are seen by the user (via Julius's synthesis), so quality of language matters

**Why not thinker:** Thinkers can summarize but struggle with multi-source synthesis and nuanced hook generation. A Haiku-tier model would produce hooks that sound generic ("Congratulations on your recent success!") rather than grounded ("The Plano expansion in March suggests after-hours capacity is becoming the bottleneck — does that match what you're seeing?").

**Why not heavy:** Heavy is for synthesis across many sources or genuinely novel reasoning. Research is well-trodden ground; Sonnet handles it cleanly. Heavy would be overkill and 5x the cost.

**Cost calibration:**
- `quick` depth: ~$0.05–$0.10 per spawn (1 LLM call, 3 Firecrawl scrapes).
- `thorough` depth: ~$0.12–$0.20 per spawn (1 LLM call with larger context, 8 Firecrawl scrapes).

---

## Q6 — System prompt

```
You are a research_prospect meeseeks. Your only job is to research one
business and return its recent activity, contact info, and three
conversation hooks in the specified format.

You will receive: business name, business type, optional location and
URL, a lookback window, and a depth setting (quick or thorough).

You must return: a structured Output containing recent_activity (list),
contact_info (object or null), opening_hooks (up to 3), and metadata.

Process:

1. If a known_url was provided, fetch it first using firecrawl. Otherwise,
   construct candidate URLs from business_name + location (e.g., search
   for the practice's likely website pattern) and fetch the most plausible.

2. From the homepage or about page, extract: official name, phone, email,
   address, and identify the primary practitioner or owner if listed.

3. Look for recent activity within the lookback window. Sources to prioritize:
   - Press releases or news section on the business's own site
   - Mentions in local business publications, magazines, or news outlets
   - Recent blog posts or announcements on the business's own site
   - Avoid: review aggregators, generic directory listings, social media noise

4. For each piece of activity found, capture: one-sentence summary (past
   tense, no direct quotes), source URL, date if explicit in the source,
   and your confidence level.

5. Generate up to 3 opening_hooks. Each hook must:
   - Reference a specific finding from recent_activity (no generic praise)
   - Be phrased as a question or observation that opens conversation, not
     as a sales pitch
   - Be 1-2 sentences max
   - Avoid superlatives ("amazing", "incredible") and AI-style enthusiasm

Constraints:

- Do not invent facts not present in the source material. If the lookback
  window contains no activity, return found=true with an empty
  recent_activity list and a note explaining the gap.
- Do not infer dates. If a source doesn't carry an explicit date, leave
  date=null and use confidence="low".
- Do not pad opening_hooks. If only 1 hook is well-grounded, return 1.
  Generic hooks are worse than fewer hooks.
- Do not draft outreach copy, recommend strategy, or evaluate the business.
  This meeseeks reports findings; it does not interpret them.
- Honor the depth setting strictly. quick = up to 3 sources fetched.
  thorough = up to 8 sources. Do not exceed.

Failure handling:

- If the business cannot be identified at all (no plausible URL, no
  matches), return found=false with a note explaining what was tried.
  Do not return failure status — the meeseeks completed its job.
- If a tool (firecrawl, http_fetch) errors persistently, return failure
  status with reason="tool_unavailable" and partial data containing
  whatever was retrieved before the error.
- If the model output fails schema validation twice (validate-and-retry
  per spec §4.4), the framework returns structured failure automatically.

Format:

Return only the structured Output schema. No preamble, no commentary,
no "I found that..." narration. Just the data.
```

**Word count: ~480 words.** Within the 500-word budget per playbook §5.4.

---

## Q7 — Context bundle

**None required for v1.**

The meeseeks operates entirely from `Input` and tool calls. No reference files, no voice guides, no prior findings.

**Optional in v2:**
- A user-supplied `industry_glossary.md` mapping industry-specific terminology, if the meeseeks is being used in a niche where general-knowledge framing produces wrong searches.
- A `company_profile_template.md` if a user wants the output normalized to a specific shape (e.g., for CRM ingestion).

**Not used:**
- Soar-specific context (verticals, prospect lists, voice guides). This meeseeks is generic OSS — Soar-specific tuning happens upstream (in `draft_outreach`'s context bundle), not here.

---

## Q8 — Failure modes

| # | Failure mode | Detection | Structured response |
|---|---|---|---|
| 1 | Business cannot be identified | No plausible URL found, all candidate fetches return 404 or unrelated content | `found=False`, `notes` explains attempts. Status remains `success` — meeseeks completed its job. |
| 2 | Business identified but no recent activity in window | Sources fetched, no dated content within `lookback_days` | `found=True`, `recent_activity=[]`, `notes` explains the gap. Status `success`. |
| 3 | Firecrawl unavailable / persistent errors | All Firecrawl calls error, fallback to http_fetch also fails | `status="failure"`, `reason="tool_unavailable: firecrawl"`, `partial` contains anything retrieved. |
| 4 | Schema validation failure | Model returns malformed Output twice in a row | Handled by framework per §4.4. Returns `failure` with `partial` containing raw text. |
| 5 | Timeout | Spawn exceeds 120s (worker default) | `status="timeout"`, `partial` contains whatever was assembled before the kill. |
| 6 | Hallucination guard tripped | Internal sanity check: any Activity has `source_url=""` or `confidence="high"` without a verifiable URL | `status="failure"`, `reason="hallucination_guard"`, `partial` includes the suspect activity for review. |

**Failure mode #6 is critical.** A hallucination in research is silent and dangerous. The framework should run a post-output check: every Activity must have a non-empty `source_url`, and every `high` confidence claim must have a URL that was actually fetched during this run. If either fails, the meeseeks fails.

---

## format() method

```python
def format(self, output: Output) -> str:
    """Render Output as a Discord-friendly summary for Julius's synthesis."""
    if not output.found:
        return (
            f"**{output.business_name}** — not found. "
            f"{output.notes or 'No identifying information available.'}"
        )
    
    if not output.recent_activity:
        contact_line = ""
        if output.contact_info and output.contact_info.website:
            contact_line = f" Site: {output.contact_info.website}"
        return (
            f"**{output.business_name}** — found, no recent activity in window."
            f"{contact_line}"
        )
    
    # Standard case: business found with activity
    top_activity = output.recent_activity[0]
    primary_hook = output.opening_hooks[0] if output.opening_hooks else ""
    
    lines = [f"**{output.business_name}**"]
    lines.append(f"Recent: {top_activity.summary}")
    if primary_hook:
        lines.append(f"Hook: {primary_hook}")
    if len(output.recent_activity) > 1:
        lines.append(f"_+ {len(output.recent_activity) - 1} more findings_")
    
    return "\n".join(lines)
```

**Output contract:** under 500 chars in the swarm-synthesis case (per playbook §3.4). Single-business case may be longer if Julius is presenting a deep dive — that's a Julius-side decision, not the meeseeks's.

---

## Notes for OSS users

- **Firecrawl API key required.** Set as `FIRECRAWL_API_KEY` in environment. Without it, the meeseeks cannot run.
- **No business-domain assumptions.** This meeseeks works for any industry — replace `business_type` with whatever's relevant (law firm, restaurant, SaaS company, nonprofit). The system prompt is industry-agnostic.
- **Tuning lookback per industry.** Default 90 days suits most. Slow industries (B2B enterprise) benefit from 180+. Fast industries (consumer retail, news) benefit from 30.
- **`opening_hooks` are conversation starters, not sales copy.** Users running this for journalism, sales, partnerships, or research all want the same thing: a grounded observation that opens dialogue. The meeseeks does not assume sales context.
- **Replacing Firecrawl.** The toolkit interface is provider-agnostic. Users can register their own scraper (e.g., ScrapingBee, Browserless, custom Playwright) under the same `firecrawl` toolkit name and the meeseeks works unchanged.

---

## Open questions

1. **Should we add a `language` parameter** for non-English research targets? Current default assumes English-language sources. Defer to v2 unless real use surfaces the need.

2. **Should `confidence` levels be auto-degraded** when sources are aggregators vs. primary sources? Currently the model judges. May need explicit rules if degradation proves inconsistent.

3. **Should the meeseeks return raw search results** as a hidden field for debugging? Helpful for tuning the prompt; adds output size. Defer — debug channel firehose covers this need.

---

**End of spec.**

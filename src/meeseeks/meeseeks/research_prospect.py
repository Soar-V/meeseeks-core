from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from meeseeks.registry import Meeseeks, register_meeseeks


class Activity(BaseModel):
    summary: str = Field(
        description="One-sentence description of what happened. Past tense. No quotes from source."
    )
    source_url: str = Field(
        description="Direct URL to the source. Required — every claim is attributable."
    )
    date: Optional[str] = Field(
        default=None,
        description="ISO 8601 date if found in source, else None. Do not infer dates.",
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


@register_meeseeks
class ResearchProspectMeeseeks(Meeseeks):
    name = "research_prospect"
    description = "Researches a single business and returns recent activity, contact information, and conversation hooks suitable for outreach or context-gathering."
    triggers = [
        "research {prospect}",
        "look up {business}",
        "what do we know about {name}",
    ]

    tier = "worker"
    isolation = "subprocess"
    use_framework = True
    estimated_cost_usd = 0.10
    timeout_seconds = 120
    destructive = False
    toolkits = ["research"]

    class Input(BaseModel):
        business_name: str = Field(
            description="Exact name of the business to research, as known to the user"
        )
        business_type: str = Field(
            description="Industry or category to scope the search (e.g., 'plastic surgery practice', 'HVAC contractor', 'dental clinic'). Used to disambiguate common names."
        )
        location: Optional[str] = Field(
            default=None,
            description="City, region, or state if known. Improves search precision for businesses with common names.",
        )
        lookback_days: int = Field(
            default=90,
            ge=1,
            le=365,
            description="Window for 'recent' activity. Defaults to 90 days, which catches quarterly news cycles.",
        )
        depth: Literal["quick", "thorough"] = Field(
            default="quick",
            description="quick = ~3 sources, ~30 sec, ~$0.05. thorough = ~8 sources, ~90 sec, ~$0.15.",
        )
        known_url: Optional[str] = Field(
            default=None,
            description="Business's website if known. Skips a search step and improves accuracy.",
        )

    class Output(BaseModel):
        business_name: str = Field(
            description="The business as found. May differ slightly from input if a more canonical form exists."
        )
        found: bool = Field(
            description="True if the business was successfully identified and at least one piece of information was retrieved."
        )
        recent_activity: list[Activity] = Field(
            default_factory=list,
            description="Activity within the lookback window. May be empty if found=True but nothing recent. Ordered most-recent first.",
        )
        contact_info: Optional[ContactInfo] = Field(
            default=None,
            description="None if no contact info could be verified. Partial fields are fine — populate what's known.",
        )
        opening_hooks: list[str] = Field(
            default_factory=list,
            description="Up to 3 conversation starters grounded in the recent activity. Each hook references a specific finding, not generic praise.",
        )
        notes: Optional[str] = Field(
            default=None,
            description="Free-form notes about data quality, gaps, or anything to surface to the user. Brief — under 200 chars.",
        )
        sources_consulted: int = Field(
            ge=0,
            description="How many URLs were actually fetched. For cost/effort visibility.",
        )

    def system_prompt(self, inputs: "ResearchProspectMeeseeks.Input") -> str:
        return """You are a research_prospect meeseeks. Your only job is to research one
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
no "I found that..." narration. Just the data."""

    def validate_output(
        self,
        output: "ResearchProspectMeeseeks.Output",
        fetched_urls: set,
    ) -> str | None:
        for activity in output.recent_activity:
            if not activity.source_url:
                return f"hallucination_guard: activity has empty source_url: '{activity.summary[:80]}'"
            if activity.confidence == "high" and activity.source_url not in fetched_urls:
                return (
                    f"hallucination_guard: high-confidence source_url not in fetched URLs: "
                    f"{activity.source_url}"
                )
        return None

    def format(self, output: "ResearchProspectMeeseeks.Output") -> str:
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

        top_activity = output.recent_activity[0]
        primary_hook = output.opening_hooks[0] if output.opening_hooks else ""

        lines = [f"**{output.business_name}**"]
        lines.append(f"Recent: {top_activity.summary}")
        if primary_hook:
            lines.append(f"Hook: {primary_hook}")
        if len(output.recent_activity) > 1:
            lines.append(f"_+ {len(output.recent_activity) - 1} more findings_")

        return "\n".join(lines)

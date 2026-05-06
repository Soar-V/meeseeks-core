# Meeseeks: analyze_ab_test

**Version:** 0.1
**Tier:** worker
**Toolkits:** none
**Destructive:** no
**Dynamic toolkits:** no
**Status:** draft

---

## Q1 — Single sentence description

Analyzes results from a multi-variant test, reports lift and sample-size honesty, and recommends the next iteration based on observed patterns.

---

## Q2 — Input schema

```python
from typing import Literal, Optional
from pydantic import BaseModel, Field

class MetricDefinition(BaseModel):
    name: str = Field(
        description="Metric identifier as used in variant.metrics. E.g., 'response_rate', 'click_through', 'reply_quality'."
    )
    description: str = Field(
        max_length=200,
        description="What this metric represents in plain language. E.g., 'Fraction of recipients who replied within 7 days.' Required so the meeseeks knows what it's reasoning about."
    )
    direction: Literal["higher_is_better", "lower_is_better"] = Field(
        description="higher_is_better for response rates, conversions. lower_is_better for cost-per-acquisition, time-to-response."
    )
    is_primary: bool = Field(
        default=False,
        description="True if this is the metric being optimized for. Exactly one metric should be is_primary=True. Drives the recommendation."
    )

class Variant(BaseModel):
    variant_id: str = Field(
        description="Short identifier (e.g., 'A', 'B', 'control', 'missed_revenue'). Caller's choice."
    )
    description: str = Field(
        max_length=300,
        description="What this variant is or does. E.g., 'Missed-revenue framing with audio clip CTA.' Required so the meeseeks can reason about why a variant might have performed differently."
    )
    sample_size: int = Field(
        ge=0,
        description="Number of subjects exposed to this variant. Used for honesty about confidence."
    )
    metrics: dict[str, float] = Field(
        description="Metric values for this variant, keyed by metric name from MetricDefinition. Values must align with metric definitions provided."
    )

class Input(BaseModel):
    test_name: str = Field(
        description="Short name of the test, used in output references. E.g., 'Plastic surgery cold outreach Q2 2026'."
    )
    test_objective: str = Field(
        max_length=300,
        description="What the test was trying to learn. E.g., 'Determine which framing produces higher response rate among solo-practice surgeons.' Drives the recommendation framing."
    )
    metrics_defined: list[MetricDefinition] = Field(
        min_items=1,
        max_items=10,
        description="All metrics being analyzed. Exactly one must have is_primary=True."
    )
    variants: list[Variant] = Field(
        min_items=2,
        max_items=10,
        description="Variants to compare. Minimum 2 (A/B). Maximum 10 to keep analysis tractable."
    )
    test_duration_days: Optional[int] = Field(
        default=None,
        ge=1,
        description="How long the test ran. Used for context on sample size adequacy."
    )
    minimum_sample_threshold: int = Field(
        default=30,
        ge=1,
        description="Sample size below which results are flagged as 'too small to trust'. Default 30 is a rough rule of thumb; tighten or loosen based on context."
    )
    notes: Optional[str] = Field(
        default=None,
        max_length=300,
        description="Any context the meeseeks should know that the metrics don't capture. E.g., 'Variant C went out two days late due to a deploy issue.' Affects interpretation."
    )
```

**Field notes:**

- The flexible `metrics` dict on each variant is what makes this generic. The caller defines metrics, the meeseeks reasons about them.
- Exactly one metric must be `is_primary=True`. Multiple primary metrics produce conflicting recommendations; the schema enforces a single optimization target. Secondary metrics inform the recommendation but don't drive it.
- `description` is required on both metrics and variants. Without it, the meeseeks reasons about abstract numbers and produces generic recommendations. With it, the meeseeks can identify *why* a variant outperformed.
- `minimum_sample_threshold` is the dial for "how rigorous." Default 30 catches obvious sample-size problems. Set to 100+ for higher-stakes tests; lower for exploratory pilots.
- `notes` is the escape hatch for confounds. If you know a variant was disadvantaged by something external, say so. The meeseeks weights its recommendation accordingly.

---

## Q3 — Output schema (designed for synthesis)

```python
from typing import Optional
from pydantic import BaseModel, Field

class VariantPerformance(BaseModel):
    variant_id: str
    primary_metric_value: float = Field(
        description="Value of the primary metric for this variant."
    )
    lift_vs_baseline: Optional[float] = Field(
        default=None,
        description="Percentage lift over the lowest-performing variant on the primary metric. None if this IS the baseline. Negative for variants that underperformed the baseline."
    )
    rank: int = Field(
        ge=1,
        description="Rank on the primary metric. 1 = best."
    )
    sample_adequate: bool = Field(
        description="True if sample_size >= minimum_sample_threshold."
    )
    secondary_observations: list[str] = Field(
        default_factory=list,
        max_items=3,
        description="Notable observations from secondary metrics for this variant. Brief."
    )

class Insight(BaseModel):
    observation: str = Field(
        max_length=200,
        description="One specific pattern observed in the data. Grounded in actual numbers, not vibes."
    )
    confidence: Literal["high", "medium", "low"] = Field(
        description="high = pattern holds across all variants and sample sizes are adequate. medium = pattern holds but sample size limits confidence. low = pattern is suggestive but could be noise."
    )

class Recommendation(BaseModel):
    next_action: str = Field(
        max_length=300,
        description="Specific next step. E.g., 'Roll out Variant B to full audience' or 'Re-test B and C with larger sample (n=100 each).' Must be concrete and actionable."
    )
    rationale: str = Field(
        max_length=400,
        description="Why this is the right next step given the data. References specific findings."
    )
    confidence: Literal["high", "medium", "low"] = Field(
        description="high = data clearly supports this. medium = data supports but with caveats. low = best guess given limited data."
    )

class Output(BaseModel):
    test_name: str = Field(
        description="Echoes input.test_name."
    )
    primary_metric: str = Field(
        description="Echoes the name of the primary metric for clarity."
    )
    performances: list[VariantPerformance] = Field(
        description="One entry per variant, ordered by rank (best first)."
    )
    sample_size_warning: Optional[str] = Field(
        default=None,
        max_length=300,
        description="None if all samples are adequate. Otherwise a clear statement of which variants are under-sampled and what that means for confidence."
    )
    insights: list[Insight] = Field(
        default_factory=list,
        max_items=5,
        description="Up to 5 observations grounded in the data. Empty if data is too sparse for meaningful insights."
    )
    recommendation: Recommendation = Field(
        description="The next iteration recommended by the meeseeks. Always present."
    )
    notes: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Optional meta-observations: 'Test duration was unusually short; results may be biased toward early-responder demographics.' Brief."
    )
```

**Synthesis notes:**

- `performances` is ordered by rank (best variant first). Ties broken by sample size (larger first), then by variant_id alphabetical.
- `lift_vs_baseline` is intentionally percentage-based and computed against the worst performer, not the average. This makes "Variant B is 40% better than the worst" easier to interpret than "Variant B is 12% above mean."
- `sample_size_warning` is a single field, not a per-variant flag, because it's the kind of caveat the user needs to see prominently — not buried in individual variant data. If sample sizes are inadequate, this field surfaces it loudly.
- `insights` are the meeseeks's pattern-finding. Different from the recommendation: insights describe what's true; recommendation says what to do.
- `recommendation` is always present, even on inconclusive tests. "Re-test with larger sample" is a valid recommendation. The meeseeks doesn't refuse to recommend.

---

## Q4 — Toolkits required

**None.** Pure reasoning over the structured input data.

This meeseeks runs in subprocess (worker tier requires it for isolation), but doesn't make any external tool calls. Spawn cost is dominated by the LLM call.

**Note on the no-toolkit choice:** Real statistical significance testing (chi-squared, p-values, confidence intervals) would require code execution and a `stats` toolkit. The decision (per the design discussion) is to skip formal stats in v1 and rely on lift % + sample size honesty. If formal stats become needed, that's a `compute_stats` worker meeseeks called separately.

---

## Q5 — Tier

**`worker`** (default model: Claude Sonnet, fallback: GPT-4o → DeepSeek).

**Reasoning:** The job involves:
- Comparing performance across variants on multiple metrics
- Reasoning about *why* one variant might have outperformed (linking variant descriptions to outcomes)
- Honest sample-size assessment
- Generating actionable, specific recommendations grounded in the data

This requires understanding cause-and-effect at a level thinker tiers don't reliably handle. A Haiku-tier model can compute lift and rank variants, but it'll produce generic recommendations ("test more variants") rather than specific ones ("the missed-revenue framing's higher response rate suggests urgency framing resonates; test a Q4-deadline framing as Variant D").

**Why not heavy:** Heavy is overkill for tests with 2-10 variants. Reserve Heavy for genuinely complex synthesis (e.g., analyzing 20 tests across 5 quarters to identify meta-patterns).

**Cost calibration:**
- 2 variants, simple metrics: ~$0.05–$0.08 per spawn.
- 5 variants, multiple metrics: ~$0.08–$0.12 per spawn.
- 10 variants, multiple metrics with notes: ~$0.12–$0.18 per spawn.

**Conservative estimate for approval-mode logic:** `estimated_cost_usd = 0.20` (covers max case, errs high so auto-approve is safe under $1 threshold).

---

## Q6 — System prompt

```
You are an analyze_ab_test meeseeks. Your only job is to analyze a
multi-variant test, report lift on the primary metric, surface
sample-size limitations honestly, and recommend a specific next step.

You will receive: a test name and objective, a list of metric
definitions (one is_primary), a list of 2-10 variants with metric
values and descriptions, optional duration and sample threshold,
and optional notes about confounds.

You must return: per-variant performance with rank and lift, an
optional sample-size warning, up to 5 grounded insights, and exactly
one recommendation. The recommendation is always present.

Process:

1. Identify the primary metric. Extract its values from each variant.

2. Rank variants by primary metric. For higher_is_better, descending;
   for lower_is_better, ascending. Compute lift_vs_baseline as
   percentage difference from the worst-performing variant.

3. Check sample sizes against minimum_sample_threshold. If any
   variant is under threshold, set sample_adequate=false on it and
   construct a sample_size_warning field that names the under-sampled
   variants and explains the impact:
   - "Variant C had n=12, below the 30 minimum. Its observed lift may
     be noise."
   - Be specific. "Some samples were small" is useless.

4. Look at secondary metrics. For each variant, identify up to 3
   notable observations from secondary metrics. E.g., "Higher response
   rate but slower time-to-response" or "Highest open rate but lowest
   reply quality." Skip secondaries that show no meaningful variation.

5. Generate insights — patterns observed across variants. Up to 5.
   Each insight must:
   - Reference specific variants and numbers ("Variants with urgency
     framing (B, D) outperformed informational framings (A, C) by
     22% average")
   - Set confidence honestly: high if pattern is consistent and samples
     are adequate; medium if pattern is consistent but samples limit
     confidence; low if the pattern is suggestive but could be noise
   - Avoid generic insights ("smaller samples have more variance" — this
     is true of every test and adds no value)

6. Generate the recommendation. Must be:
   - Concrete and actionable. "Test more variants" is too vague. "Add a
     Variant D combining B's urgency framing with C's social proof" is
     actionable.
   - Grounded in the rationale field, which references specific findings.
   - Honest about confidence:
     - high: data clearly supports a winner with adequate samples
     - medium: a likely winner with caveats (e.g., "B leads but n=25 is
       borderline; consider re-testing or rolling out cautiously")
     - low: data is too sparse for a strong call. Recommendation is
       usually "re-test with larger sample" or "test fewer, more
       differentiated variants."

7. If notes mention confounds, weight the recommendation accordingly.
   E.g., if a variant was disadvantaged ("Variant C went out two days
   late"), don't recommend killing it without flagging the confound.

Constraints:

- Do not call statistical significance with p-values, confidence
  intervals, or formal stats. The output is lift % + sample-size
  honesty + insight + recommendation. Formal stats are out of scope.
- Do not invent metrics not defined in input.metrics_defined.
- Do not invent variants not provided.
- Do not assume the primary metric is the only one that matters.
  Surface secondary observations even when they don't drive the
  recommendation.
- Do not produce recommendations that ignore sample size. If samples
  are inadequate, the recommendation must address that, not gloss over.
- Do not refuse to recommend on inconclusive data. "Re-test with n=100
  per variant" is a valid recommendation; "no recommendation possible"
  is not.
- Do not produce vague insights. Every insight references specific
  variants and numbers.

Failure handling:

- If exactly-one is_primary constraint is violated (zero or multiple
  primaries), return failure with reason="invalid_primary_metric".
- If a variant references a metric not in metrics_defined, return
  failure with reason="undefined_metric: <name>".
- If all sample sizes are zero, return failure with reason="no_data".

Format:

Return only the structured Output schema. No preamble, no commentary.
The recommendation field must always be populated.
```

**Word count: ~480 words.** Within the 500-word budget per playbook §5.4.

---

## Q7 — Context bundle

**None required.**

The meeseeks operates entirely from the structured `Input`. The `notes` field provides any contextual information the user wants to inject.

---

## Q8 — Failure modes

| # | Failure mode | Detection | Structured response |
|---|---|---|---|
| 1 | Invalid primary metric (zero or multiple is_primary=True) | Validation at input parse | `status="failure"`, `reason="invalid_primary_metric"`. Pre-LLM check. |
| 2 | Undefined metric referenced in variant | A variant.metrics key not in metrics_defined | `status="failure"`, `reason="undefined_metric: <name>"`. Pre-LLM check. |
| 3 | All sample sizes zero | `sum(v.sample_size for v in variants) == 0` | `status="failure"`, `reason="no_data"`. Pre-LLM check. |
| 4 | Schema validation failure on output | Output malformed | Framework validate-and-retry per §4.4. Returns failure after two attempts. |
| 5 | Lift calculation mathematical error | Internal sanity check: ranks don't align with primary metric values, or lifts don't compute correctly | `status="failure"`, `reason="math_error"`, `partial` includes the inconsistent calculation. |
| 6 | Recommendation field empty or generic | Internal check: recommendation.next_action is empty, "no recommendation possible", or matches a generic-recommendation blocklist | `status="failure"`, `reason="recommendation_too_vague"`, retry once with stronger prompt. |
| 7 | Insights reference undefined variants | Internal check: insight text mentions variant_id not in input.variants | `status="failure"`, `reason="hallucination_guard"`, `partial` includes the suspect insight. |
| 8 | Timeout | Spawn exceeds 120s (worker default; rare for this meeseeks) | `status="timeout"`, `partial` contains whatever was assembled. |

**Failure modes #1, #2, and #3 are pre-LLM checks** — the framework validates input shape before spending money on a model call. Fail fast.

**Failure mode #5 is a post-LLM math check** — verify rank ordering and lift calculations actually correspond to the metric values. Without this, the meeseeks could rank Variant B first while reporting Variant C had the highest value (a real LLM failure mode on numerical reasoning).

**Failure mode #6 is the anti-vagueness guard.** Without it, models default to "test more, gather more data" recommendations that are technically valid but useless. The guard forces a concrete next step or fails honestly.

---

## format() method

```python
def format(self, output: Output) -> str:
    """Render Output as a Discord-friendly summary for Julius's synthesis."""
    lines = []
    
    # Header with primary metric
    lines.append(f"**A/B test: {output.test_name}**")
    lines.append(f"_Primary metric: {output.primary_metric}_")
    
    # Sample size warning surfaced loudly if present
    if output.sample_size_warning:
        lines.append(f"⚠️ {output.sample_size_warning}")
    
    # Performance table — top 3 inline
    lines.append("")
    lines.append("**Results:**")
    for perf in output.performances[:3]:
        lift_str = ""
        if perf.lift_vs_baseline is not None:
            sign = "+" if perf.lift_vs_baseline >= 0 else ""
            lift_str = f" ({sign}{perf.lift_vs_baseline:.0f}% vs baseline)"
        sample_flag = "" if perf.sample_adequate else " ⚠️ low sample"
        lines.append(
            f"{perf.rank}. **{perf.variant_id}** — "
            f"{perf.primary_metric_value:.3f}{lift_str}{sample_flag}"
        )
    
    if len(output.performances) > 3:
        lines.append(f"_+ {len(output.performances) - 3} more variants_")
    
    # Top insights (max 3 inline)
    if output.insights:
        lines.append("")
        lines.append("**Insights:**")
        for insight in output.insights[:3]:
            confidence_marker = ""
            if insight.confidence == "low":
                confidence_marker = " _(low confidence)_"
            lines.append(f"• {insight.observation}{confidence_marker}")
    
    # Recommendation — always shown
    lines.append("")
    lines.append(f"**Recommended next:** {output.recommendation.next_action}")
    if output.recommendation.confidence != "high":
        lines.append(f"_{output.recommendation.confidence} confidence — {output.recommendation.rationale}_")
    
    if output.notes:
        lines.append("")
        lines.append(f"_{output.notes}_")
    
    return "\n".join(lines)
```

**Output contract:** under 800 chars in typical cases. The sample-size warning is positioned prominently when present (right after the header) because it's the caveat that affects how to interpret everything below it. The recommendation is always shown, with rationale exposed when confidence is medium or low (high-confidence recommendations don't need their reasoning surfaced inline — Julius can offer it on request).

---

## Notes for OSS users

- **The schema is metric-agnostic.** Plug in any metrics: response rates, conversion percentages, time-to-completion (lower is better), revenue per visitor, NPS scores. Define each metric's direction and the meeseeks reasons accordingly.
- **`description` fields are higher-leverage than they look.** A meeseeks reasoning over `{response_rate: 0.18}` produces generic insights. The same meeseeks reasoning over `{response_rate: 0.18}` *plus* "Variant B uses a missed-revenue framing with a 7-day deadline" produces grounded insights. Spend the 30 seconds on descriptions.
- **The `minimum_sample_threshold` default (30) is a heuristic, not a rule.** For high-stakes tests (e.g., pricing tests on a SaaS product), use 100+. For exploratory directional tests, 20-30 is fine.
- **No formal statistics.** This meeseeks gives you lift % and sample-size honesty, not p-values. If you need formal stats for a reporting context (board meeting, scientific paper), pair this with a separate stats meeseeks or external tool.
- **Use the `notes` field for confounds.** If you know one variant was disadvantaged (delayed deploy, smaller audience, served on different days), say so. The meeseeks weights its recommendation accordingly.
- **The recommendation always comes back.** Even on inconclusive tests. "Re-test with larger sample" is the recommendation when data is sparse. Useful — it tells you the test isn't done, instead of leaving you wondering.

---

## Open questions

1. **Should the meeseeks accept multiple test runs over time** (e.g., "here are tests run weekly for the last 8 weeks")? Useful for trend analysis but expands scope significantly. Defer to a `analyze_test_history` meeseeks if real demand emerges.

2. **Should there be a "guardrail metrics" concept** (metrics you don't optimize for but want to ensure don't degrade)? Common in product A/B testing. Adds schema complexity. Defer until evidence shows demand.

3. **Should sample-size threshold be metric-specific** (different thresholds for response rate vs. conversion rate)? Currently one threshold applies to all variants. More granular thresholds add precision but also configuration burden.

4. **Should the meeseeks suggest the *type* of next test** (e.g., "test specific to mobile users" vs. "test with larger sample")? Currently next_action is open-ended. Forcing a structured taxonomy might constrain useful flexibility.

---

**End of spec.**

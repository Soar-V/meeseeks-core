import os
import pytest
from pydantic import BaseModel
from meeseeks.registry import register_meeseeks, Meeseeks
from meeseeks.summon import summon
from meeseeks.budget import today_total


pytestmark = pytest.mark.skipif(
    not os.environ.get("OPENROUTER_API_KEY"), reason="No OPENROUTER_API_KEY"
)


@register_meeseeks
class SummarizeMeeseeks(Meeseeks):
    name = "summarize_e2e"
    description = "Summarize text"
    tier = "thinker"
    isolation = "inline"
    use_framework = False
    timeout_seconds = 30

    class Input(BaseModel):
        text: str

    class Output(BaseModel):
        summary: str
        word_count: int

    def system_prompt(self, inputs):
        return f"Summarize in one sentence: '{inputs.text}'. Return JSON with 'summary' (str) and 'word_count' (int, word count of summary)."


def test_e2e_summon_and_budget():
    before = today_total()
    result = summon(
        SummarizeMeeseeks,
        SummarizeMeeseeks.Input(text="The quick brown fox jumped over the lazy dog. It was a Tuesday.")
    )
    assert result.status == "success"
    assert len(result.data.summary) > 10
    assert result.data.word_count > 0
    after = today_total()
    assert after > before, "budget should have recorded a cost"
    print(f"\nSummary: {result.data.summary}")
    print(f"Cost recorded: ${after - before:.4f}")

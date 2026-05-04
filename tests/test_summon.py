import os
import pytest
from pydantic import BaseModel
from meeseeks.registry import register_meeseeks, Meeseeks
from meeseeks.summon import summon


pytestmark = pytest.mark.skipif(
    not os.environ.get("OPENROUTER_API_KEY"), reason="No OPENROUTER_API_KEY"
)


@register_meeseeks
class ClassifyMeeseeks(Meeseeks):
    name = "classify_test"
    description = "Classify sentiment"
    tier = "thinker"
    isolation = "inline"
    use_framework = False
    timeout_seconds = 30

    class Input(BaseModel):
        text: str

    class Output(BaseModel):
        sentiment: str  # positive | negative | neutral
        confidence: float

    def system_prompt(self, inputs):
        return f"Classify the sentiment of: '{inputs.text}'. Return JSON with 'sentiment' and 'confidence' (0-1)."

    def format(self, output):
        return f"{output.sentiment} ({output.confidence:.0%})"


def test_inline_summon():
    result = summon(ClassifyMeeseeks, ClassifyMeeseeks.Input(text="I love this product!"))
    assert result.status == "success"
    assert result.data.sentiment in ["positive", "negative", "neutral"]
    assert 0 <= result.data.confidence <= 1
    assert result.cost.total_tokens > 0
    assert result.duration_ms > 0
    print(f"\nResult: {result.data}")
    print(f"Cost: ${result.cost.cost_usd:.4f}, {result.cost.total_tokens} tokens")

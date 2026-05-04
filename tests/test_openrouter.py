import os
import pytest
from meeseeks.providers.openrouter import OpenRouterProvider

pytestmark = pytest.mark.skipif(
    not os.environ.get("OPENROUTER_API_KEY"), reason="No OPENROUTER_API_KEY"
)

def test_basic_chat():
    p = OpenRouterProvider()
    content, usage, model = p.chat_with_fallback(
        messages=[{"role": "user", "content": "Reply with exactly: pong"}],
        tier="thinker",
    )
    assert "pong" in content.lower()
    assert usage.total_tokens > 0
    print(f"model={model}, cost=${usage.cost_usd:.4f}")

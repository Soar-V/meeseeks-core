from meeseeks.contracts import MeeseeksResult, TokenUsage
from pydantic import BaseModel


class FakeOutput(BaseModel):
    summary: str


def test_success_result():
    cost = TokenUsage(prompt_tokens=100, completion_tokens=50, cost_usd=0.01)
    result = MeeseeksResult[FakeOutput].success(
        data=FakeOutput(summary="test"), cost=cost, duration_ms=500
    )
    assert result.status == "success"
    assert result.data.summary == "test"
    assert result.cost.cost_usd == 0.01
    assert len(result.meeseeks_id) == 8


def test_failure_result():
    result = MeeseeksResult.failure(reason="schema_mismatch")
    assert result.status == "failure"
    assert result.data is None
    assert result.reason == "schema_mismatch"


def test_timeout_result():
    result = MeeseeksResult.timeout()
    assert result.status == "timeout"


def test_grand_total():
    cost = TokenUsage(cost_usd=0.05, tool_cost_usd=0.02)
    assert cost.grand_total_usd == 0.07

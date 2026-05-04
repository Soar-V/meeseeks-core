"""Test that the top-level public API surface works as documented."""
from meeseeks import (
    summon,
    register_meeseeks,
    Meeseeks,
    MeeseeksResult,
    TokenUsage,
    StructuredOutputParser,
    today_total,
    cost_breakdown,
)
from meeseeks.parser import StructuredOutputParser as SOP2
from pydantic import BaseModel


def test_top_level_imports():
    assert callable(summon)
    assert callable(register_meeseeks)
    assert MeeseeksResult is not None
    assert TokenUsage is not None
    assert StructuredOutputParser is SOP2  # same object, not a copy


def test_meeseeks_result_via_top_level():
    r = MeeseeksResult.failure(reason="test")
    assert r.status == "failure"
    assert len(r.meeseeks_id) == 8


def test_token_usage_via_top_level():
    u = TokenUsage(cost_usd=0.01, tool_cost_usd=0.005)
    assert u.grand_total_usd == 0.015


def test_declare_meeseeks_via_top_level():
    @register_meeseeks
    class TopLevelTest(Meeseeks):
        name = "top_level_test"
        description = "test"
        tier = "thinker"
        isolation = "inline"

        class Input(BaseModel):
            x: int

        class Output(BaseModel):
            y: int

        def system_prompt(self, inputs):
            return f"double {inputs.x}"

    m = TopLevelTest()
    assert m.name == "top_level_test"

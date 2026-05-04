"""
meeseeks-core — single-purpose ephemeral AI agents.

Typical usage::

    from meeseeks import summon, register_meeseeks, MeeseeksResult
    from pydantic import BaseModel

    @register_meeseeks
    class MyTask(Meeseeks):
        name = "my_task"
        tier = "thinker"
        isolation = "inline"
        class Input(BaseModel): text: str
        class Output(BaseModel): result: str
        def system_prompt(self, inputs): return f"Do: {inputs.text}"

    result = summon(MyTask, MyTask.Input(text="hello"))
    assert result.status == "success"
"""

from meeseeks.summon import summon                            # noqa: F401
from meeseeks.registry import register_meeseeks, Meeseeks    # noqa: F401
from meeseeks.contracts import MeeseeksResult, TokenUsage    # noqa: F401
from meeseeks.parser import StructuredOutputParser           # noqa: F401
from meeseeks.budget import today_total, cost_breakdown      # noqa: F401

__all__ = [
    "summon",
    "register_meeseeks",
    "Meeseeks",
    "MeeseeksResult",
    "TokenUsage",
    "StructuredOutputParser",
    "today_total",
    "cost_breakdown",
]

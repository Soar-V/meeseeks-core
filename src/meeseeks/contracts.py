from __future__ import annotations
from typing import Generic, Literal, TypeVar
from pydantic import BaseModel, Field
import uuid

T = TypeVar("T")


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    tool_cost_usd: float = 0.0

    @property
    def grand_total_usd(self) -> float:
        return self.cost_usd + self.tool_cost_usd


class MeeseeksResult(BaseModel, Generic[T]):
    status: Literal["success", "failure", "timeout"]
    data: T | None = None
    reason: str | None = None
    partial: dict | None = None
    cost: TokenUsage = Field(default_factory=TokenUsage)
    duration_ms: int = 0
    meeseeks_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])

    @classmethod
    def success(cls, data: T, cost: TokenUsage, duration_ms: int) -> "MeeseeksResult[T]":
        return cls(status="success", data=data, cost=cost, duration_ms=duration_ms)

    @classmethod
    def failure(cls, reason: str, partial: dict | None = None, cost: TokenUsage | None = None) -> "MeeseeksResult":
        return cls(status="failure", reason=reason, partial=partial, cost=cost or TokenUsage())

    @classmethod
    def timeout(cls, partial: dict | None = None, cost: TokenUsage | None = None) -> "MeeseeksResult":
        return cls(status="timeout", reason="meeseeks timed out", partial=partial, cost=cost or TokenUsage())


# Back-compat re-export — parser lives in meeseeks.parser now
from meeseeks.parser import StructuredOutputParser  # noqa: E402, F401

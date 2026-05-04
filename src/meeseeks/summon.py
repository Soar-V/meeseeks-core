from __future__ import annotations
import time
from typing import Type, TypeVar
from pydantic import BaseModel

from meeseeks.contracts import MeeseeksResult, TokenUsage, StructuredOutputParser
from meeseeks.framework_prompt import FRAMEWORK_PROMPT
from meeseeks.providers.openrouter import OpenRouterProvider
from meeseeks.registry import Meeseeks
from meeseeks.budget import record_run

T = TypeVar("T", bound=BaseModel)

# 2000 token cap on output — rough char estimate (§4.2)
OUTPUT_CHAR_CAP = 8000


def summon(
    meeseeks_cls: Type[Meeseeks],
    inputs: Meeseeks.Input,
    provider: OpenRouterProvider | None = None,
) -> MeeseeksResult:
    """
    Summon a meeseeks. Routes to inline (thinker) or subprocess (worker/heavy)
    based on meeseeks_cls.isolation.
    """
    if provider is None:
        provider = OpenRouterProvider()

    if meeseeks_cls.isolation == "inline":
        return _summon_inline(meeseeks_cls, inputs, provider)
    else:
        return _summon_subprocess(meeseeks_cls, inputs, provider)


def _summon_inline(
    meeseeks_cls: Type[Meeseeks],
    inputs: Meeseeks.Input,
    provider: OpenRouterProvider,
) -> MeeseeksResult:
    start = time.monotonic()
    meeseeks = meeseeks_cls()

    system = (FRAMEWORK_PROMPT + "\n\n" if meeseeks_cls.use_framework else "") + meeseeks.system_prompt(inputs)
    user_msg = f"Inputs:\n{inputs.model_dump_json(indent=2)}"

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_msg},
    ]

    parser = StructuredOutputParser(
        schema=meeseeks_cls.Output,
        provider=provider,
        model=meeseeks_cls.tier,
    )

    parsed, usage, failure_reason = parser.parse_with_retry(
        messages, timeout_seconds=meeseeks_cls.timeout_seconds
    )
    duration_ms = int((time.monotonic() - start) * 1000)

    if parsed is None:
        result = MeeseeksResult.failure(
            reason=failure_reason or "parse failed",
            cost=usage,
        )
    else:
        result = MeeseeksResult.success(data=parsed, cost=usage, duration_ms=duration_ms)

    record_run(
        meeseeks_name=meeseeks_cls.name,
        meeseeks_id=result.meeseeks_id,
        status=result.status,
        cost=result.cost,
        duration_ms=result.duration_ms,
    )

    return result


def _summon_subprocess(
    meeseeks_cls: Type[Meeseeks],
    inputs: Meeseeks.Input,
    provider: OpenRouterProvider,
) -> MeeseeksResult:
    """Week 1: subprocess mode falls back to inline until Build 5 implements full subprocess."""
    # TODO: Build 5 — real subprocess isolation with multiprocessing.spawn
    return _summon_inline(meeseeks_cls, inputs, provider)

from __future__ import annotations
import time
from typing import Type, TypeVar
from pydantic import BaseModel

from meeseeks.contracts import MeeseeksResult, TokenUsage
from meeseeks.parser import StructuredOutputParser
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
        tier=meeseeks_cls.tier,
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
    """§3.2: Real subprocess isolation via multiprocessing.spawn.

    The meeseeks class must be importable by module path (defined at module level).
    API key is passed explicitly — spawn does not inherit parent env vars.
    """
    import os
    import multiprocessing
    import queue as queue_mod
    from meeseeks.isolation.subprocess_runner import _worker_entry
    import sys

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    ctx = multiprocessing.get_context("spawn")
    result_queue = ctx.Queue()

    # Pass sys.path so the subprocess can find the src/ layout
    extra_sys_path = [p for p in sys.path if p]

    proc = ctx.Process(
        target=_worker_entry,
        args=(
            meeseeks_cls.__module__,
            meeseeks_cls.__name__,
            inputs.model_dump_json(),
            result_queue,
            api_key,
            extra_sys_path,
        ),
        daemon=True,  # auto-cleanup if parent dies
    )
    start = time.monotonic()
    proc.start()

    # Wait for timeout
    proc.join(timeout=meeseeks_cls.timeout_seconds)
    duration_ms = int((time.monotonic() - start) * 1000)

    if proc.is_alive():
        # Timed out — kill and return timeout envelope
        proc.kill()
        proc.join(3)
        result = MeeseeksResult.timeout()
    elif proc.exitcode is not None and proc.exitcode < 0:
        # Killed by signal (crash / segfault)
        result = MeeseeksResult.failure(
            reason=f"worker killed by signal {-proc.exitcode}",
        )
    else:
        # Try to get result from queue
        try:
            raw = result_queue.get(timeout=2)
            # Reconstruct MeeseeksResult — re-parse data with the Output schema
            # (Generic[T] is erased at runtime so model_validate leaves data as dict)
            result = MeeseeksResult.model_validate(raw)
            if result.status == "success" and isinstance(result.data, dict):
                result = result.model_copy(
                    update={"data": meeseeks_cls.Output.model_validate(result.data)}
                )
        except queue_mod.Empty:
            result = MeeseeksResult.failure(reason="worker exited without result")

    # Stamp duration on success if worker didn't set it (worker sets its own)
    if result.status == "success" and result.duration_ms == 0:
        result = result.model_copy(update={"duration_ms": duration_ms})

    record_run(
        meeseeks_name=meeseeks_cls.name,
        meeseeks_id=result.meeseeks_id,
        status=result.status,
        cost=result.cost,
        duration_ms=result.duration_ms,
    )
    return result

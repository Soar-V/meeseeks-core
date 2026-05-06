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
from meeseeks.discord_logger import log_spawn, log_complete

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
    # Guard: verify class is actually registered — catches callers that pass
    # a bare string name or a stub object with no proper registration.
    if not hasattr(meeseeks_cls, "name") or not meeseeks_cls.name:
        return MeeseeksResult.failure(reason="summon() called with unregistered or unnamed meeseeks class")

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
    import uuid, inspect, asyncio

    start = time.monotonic()
    meeseeks = meeseeks_cls()
    spawn_id = uuid.uuid4().hex[:8]

    log_spawn(spawn_id, meeseeks_cls.name, meeseeks_cls.tier,
              meeseeks_cls.estimated_cost_usd, inputs.model_dump_json()[:120])

    if not meeseeks_cls.use_framework:
        # Bypass LLM entirely — call run() directly (sync or async)
        try:
            retval = meeseeks.run(inputs)
            if inspect.isawaitable(retval):
                retval = asyncio.run(retval)
            duration_ms = max(1, int((time.monotonic() - start) * 1000))
            result = MeeseeksResult.success(data=retval, cost=TokenUsage(), duration_ms=duration_ms)
        except Exception as exc:
            duration_ms = max(1, int((time.monotonic() - start) * 1000))
            result = MeeseeksResult.failure(reason=str(exc))
            result = result.model_copy(update={"duration_ms": duration_ms})
    else:
        system = FRAMEWORK_PROMPT + "\n\n" + meeseeks.system_prompt(inputs)
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
            result = MeeseeksResult.failure(reason=failure_reason or "parse failed", cost=usage)
            result = result.model_copy(update={"duration_ms": duration_ms})
        else:
            result = MeeseeksResult.success(data=parsed, cost=usage, duration_ms=duration_ms)

    result = result.model_copy(update={"meeseeks_id": spawn_id})
    log_complete(spawn_id, result.status, result.cost.cost_usd, result.duration_ms)

    record_run(
        meeseeks_name=meeseeks_cls.name,
        meeseeks_id=result.meeseeks_id,
        status=result.status,
        cost=result.cost,
        duration_ms=result.duration_ms,
    )

    return result


# Module-level semaphores created once — multiprocessing.Semaphore uses OS primitives
# and IS shared across spawned children when passed explicitly as an argument.
# (Module-level globals are NOT shared with spawn — OS semaphores passed via args ARE.)
import threading as _threading
_SPAWN_CTX = None
_WORKER_SEM = None
_THINKER_SEM = None
_SEM_INIT_LOCK = _threading.Lock()


def _get_semaphore(tier: str):
    """Return (or lazily create) the shared semaphore for this tier. Thread-safe."""
    global _SPAWN_CTX, _WORKER_SEM, _THINKER_SEM
    if _SPAWN_CTX is None:
        with _SEM_INIT_LOCK:
            if _SPAWN_CTX is None:
                import multiprocessing
                _SPAWN_CTX = multiprocessing.get_context("spawn")
                _WORKER_SEM = _SPAWN_CTX.Semaphore(5)
                _THINKER_SEM = _SPAWN_CTX.Semaphore(20)
    return _THINKER_SEM if tier == "thinker" else _WORKER_SEM


def _summon_subprocess(
    meeseeks_cls: Type[Meeseeks],
    inputs: Meeseeks.Input,
    provider: OpenRouterProvider,
) -> MeeseeksResult:
    """§3.2: Real subprocess isolation via multiprocessing.spawn.

    The meeseeks class must be importable by module path (defined at module level).
    API key is passed explicitly — spawn does not inherit parent env vars.
    Semaphore is created in parent from spawn context and passed to child —
    this is the correct way to share a semaphore with spawned processes.
    """
    import os
    import queue as queue_mod
    import uuid
    from meeseeks.isolation.subprocess_runner import _worker_entry
    import sys

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    sem = _get_semaphore(meeseeks_cls.tier)
    ctx = _SPAWN_CTX
    result_queue = ctx.Queue()

    # Pass sys.path so the subprocess can find the src/ layout
    extra_sys_path = [p for p in sys.path if p]

    # Generate spawn_id in parent for consistent SPAWN/COMPLETE logging
    spawn_id = uuid.uuid4().hex[:8]
    log_spawn(spawn_id, meeseeks_cls.name, meeseeks_cls.tier,
              meeseeks_cls.estimated_cost_usd, inputs.model_dump_json()[:120])

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

    # Acquire semaphore in parent before spawning — blocks here when at cap.
    # Release is guaranteed via try/finally regardless of child outcome.
    sem.acquire()
    start = time.monotonic()
    try:
        proc.start()
        # Timeout = meeseeks deadline. If child blocks on API, this fires first.
        proc.join(timeout=meeseeks_cls.timeout_seconds)
        duration_ms = int((time.monotonic() - start) * 1000)

        if proc.is_alive():
            proc.kill()
            proc.join(3)
            result = MeeseeksResult.timeout()
        elif proc.exitcode is not None and proc.exitcode < 0:
            result = MeeseeksResult.failure(
                reason=f"worker killed by signal {-proc.exitcode}",
            )
        else:
            try:
                raw = result_queue.get(timeout=2)
                result = MeeseeksResult.model_validate(raw)
                if result.status == "success" and isinstance(result.data, dict):
                    result = result.model_copy(
                        update={"data": meeseeks_cls.Output.model_validate(result.data)}
                    )
            except queue_mod.Empty:
                result = MeeseeksResult.failure(reason="worker exited without result")
    finally:
        sem.release()   # always returns slot — no leak on timeout, crash, or signal

    # Stamp spawn_id + duration (use parent wall-clock when child reported 0)
    result = result.model_copy(update={"meeseeks_id": spawn_id})
    if result.duration_ms == 0:
        result = result.model_copy(update={"duration_ms": duration_ms})

    log_complete(spawn_id, result.status, result.cost.cost_usd, result.duration_ms)

    record_run(
        meeseeks_name=meeseeks_cls.name,
        meeseeks_id=result.meeseeks_id,
        status=result.status,
        cost=result.cost,
        duration_ms=result.duration_ms,
    )
    return result

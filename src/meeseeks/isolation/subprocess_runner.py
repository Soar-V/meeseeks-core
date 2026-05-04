from __future__ import annotations
import importlib
import time


def _worker_entry(
    meeseeks_cls_module: str,
    meeseeks_cls_name: str,
    inputs_json: str,
    result_queue,   # multiprocessing.Queue — typed loosely to avoid pickle issues
    api_key: str,
    extra_sys_path: list[str] | None = None,
) -> None:
    """
    Subprocess worker entry point (§3.2).

    No semaphore here — the parent acquires the semaphore before spawning
    and releases it after the process exits. This is the only pickle-safe
    approach with multiprocessing.spawn.
    """
    if extra_sys_path:
        import sys
        for p in reversed(extra_sys_path):
            if p not in sys.path:
                sys.path.insert(0, p)
    try:
        module = importlib.import_module(meeseeks_cls_module)
        meeseeks_cls = getattr(module, meeseeks_cls_name)
        meeseeks = meeseeks_cls()
        inputs = meeseeks_cls.Input.model_validate_json(inputs_json)

        from meeseeks.framework_prompt import FRAMEWORK_PROMPT
        system = (FRAMEWORK_PROMPT + "\n\n" if meeseeks_cls.use_framework else "") + meeseeks.system_prompt(inputs)
        user_msg = f"Inputs:\n{inputs.model_dump_json(indent=2)}"
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ]

        from meeseeks.providers.openrouter import OpenRouterProvider
        provider = OpenRouterProvider(api_key=api_key)

        from meeseeks.parser import StructuredOutputParser
        start = time.monotonic()
        parser = StructuredOutputParser(
            schema=meeseeks_cls.Output,
            provider=provider,
            tier=meeseeks_cls.tier,
        )
        parsed, usage, failure_reason = parser.parse_with_retry(
            messages, timeout_seconds=meeseeks_cls.timeout_seconds
        )
        duration_ms = int((time.monotonic() - start) * 1000)

        from meeseeks.contracts import MeeseeksResult
        if parsed is None:
            result = MeeseeksResult.failure(reason=failure_reason or "parse failed", cost=usage)
        else:
            result = MeeseeksResult.success(data=parsed, cost=usage, duration_ms=duration_ms)

        result_queue.put(result.model_dump())
    except Exception as e:
        from meeseeks.contracts import MeeseeksResult
        result = MeeseeksResult.failure(reason=f"worker exception: {e}")
        result_queue.put(result.model_dump())

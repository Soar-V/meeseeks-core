from __future__ import annotations
import importlib
import inspect
import json
import time
from typing import Any, Callable


# ── Tool spec helpers ─────────────────────────────────────────────────────

def _python_type_to_json(annotation) -> dict:
    """Convert a Python type annotation to a JSON schema type dict."""
    import typing
    origin = getattr(annotation, "__origin__", None)

    # Optional[X] → unwrap to X, mark nullable
    if origin is typing.Union:
        args = [a for a in annotation.__args__ if a is not type(None)]
        if args:
            return _python_type_to_json(args[0])

    if annotation is str or annotation is inspect.Parameter.empty:
        return {"type": "string"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is bool:
        return {"type": "boolean"}
    if origin is dict or annotation is dict:
        return {"type": "object"}
    return {"type": "string"}  # safe fallback


def _fn_to_openai_tool(fn: Callable) -> dict:
    """Convert a Python function to an OpenAI-format tool spec.

    Uses inspect.signature + type annotations + docstring.
    Parameters with defaults are optional; others are required.
    """
    sig = inspect.signature(fn)
    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        annotation = param.annotation
        prop = _python_type_to_json(annotation)
        prop["description"] = name  # minimal; no per-param docstring parsing
        properties[name] = prop
        if param.default is inspect.Parameter.empty:
            required.append(name)

    return {
        "type": "function",
        "function": {
            "name": fn.__name__,
            "description": (fn.__doc__ or "").strip().split("\n")[0],
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


def _build_tools_spec(toolkit_names: list[str]) -> list[dict]:
    """Resolve toolkit names to OpenAI tool specs."""
    from meeseeks.toolkits import TOOLKIT_REGISTRY
    specs = []
    for name in toolkit_names:
        toolkit_cls = TOOLKIT_REGISTRY.get(name)
        if toolkit_cls is None:
            continue
        for fn in toolkit_cls.tools:
            specs.append(_fn_to_openai_tool(fn))
    return specs


def _dispatch_tool(tool_name: str, arguments_json: str, toolkit_names: list[str]) -> tuple[str, str | None]:
    """Execute a tool call. Returns (result_str, url_if_fetch).

    url_if_fetch is the URL argument if the tool fetches a URL — used to
    populate fetched_urls for the hallucination guard.
    """
    from meeseeks.toolkits import TOOLKIT_REGISTRY

    # Find the function
    fn = None
    for name in toolkit_names:
        toolkit_cls = TOOLKIT_REGISTRY.get(name)
        if toolkit_cls is None:
            continue
        for f in toolkit_cls.tools:
            if f.__name__ == tool_name:
                fn = f
                break
        if fn:
            break

    if fn is None:
        return json.dumps({"error": f"unknown tool: {tool_name}"}), None

    try:
        kwargs = json.loads(arguments_json) if arguments_json else {}
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"bad arguments JSON: {e}"}), None

    # Capture URL before calling (for fetched_urls tracking)
    url = kwargs.get("url")

    try:
        result = fn(**kwargs)
        return json.dumps(result, default=str), url
    except Exception as e:
        return json.dumps({"error": str(e)}), url


# ── Agent loop ────────────────────────────────────────────────────────────

MAX_TOOL_CALLS = 12  # hard cap — prevents infinite loops


def _run_agent_loop(
    meeseeks,
    messages: list[dict],
    provider,
    tools_spec: list[dict],
    toolkit_names: list[str],
    output_schema,
    timeout_seconds: int,
) -> tuple[Any | None, object, str | None, set, str | None]:
    """Multi-turn agent loop for tool-using meeseeks.

    Returns:
        (parsed_output, total_usage, failure_reason, fetched_urls, raw_final_content)

    Loop:
        1. Call LLM with tools
        2. If response has tool_calls → dispatch each → append messages → loop
        3. When no tool_calls (stop_reason=end_turn or content only) → parse final content
        4. Hard cap at MAX_TOOL_CALLS total dispatches
    """
    from meeseeks.contracts import TokenUsage

    total_usage = TokenUsage()
    fetched_urls: set[str] = set()
    tool_call_count = 0
    raw_final_content: str | None = None

    current_messages = list(messages)

    while True:
        message, usage, _model = provider.chat_with_tools_fallback(
            current_messages,
            tier=meeseeks.__class__.tier,
            tools=tools_spec,
            timeout_seconds=timeout_seconds,
        )
        total_usage.prompt_tokens += usage.prompt_tokens
        total_usage.completion_tokens += usage.completion_tokens
        total_usage.total_tokens += usage.total_tokens
        total_usage.cost_usd += usage.cost_usd

        tool_calls = message.get("tool_calls") or []

        if not tool_calls:
            # No tool calls — final answer in content
            content = message.get("content") or ""
            raw_final_content = content if isinstance(content, str) else json.dumps(content)

            # Strip markdown fences
            if isinstance(content, str) and content.strip().startswith("```"):
                from meeseeks.providers.openrouter import _strip_markdown_fences
                content = _strip_markdown_fences(content)

            # Try parse to output schema
            try:
                raw = json.loads(content) if isinstance(content, str) else content
                parsed = output_schema(**raw)
                return parsed, total_usage, None, fetched_urls, raw_final_content
            except Exception as e:
                # One retry with schema error injected
                retry_messages = current_messages + [
                    {"role": "assistant", "content": raw_final_content},
                    {"role": "user", "content": (
                        f"Your output failed schema validation: {e}\n"
                        "Fix it and return valid JSON matching the required schema. No preamble."
                    )},
                ]
                message2, usage2, _m2 = provider.chat_with_tools_fallback(
                    retry_messages,
                    tier=meeseeks.__class__.tier,
                    tools=tools_spec,
                    timeout_seconds=timeout_seconds,
                )
                total_usage.prompt_tokens += usage2.prompt_tokens
                total_usage.completion_tokens += usage2.completion_tokens
                total_usage.total_tokens += usage2.total_tokens
                total_usage.cost_usd += usage2.cost_usd

                content2 = message2.get("content") or ""
                if isinstance(content2, str) and content2.strip().startswith("```"):
                    from meeseeks.providers.openrouter import _strip_markdown_fences
                    content2 = _strip_markdown_fences(content2)
                raw_final_content = content2 if isinstance(content2, str) else json.dumps(content2)

                try:
                    raw2 = json.loads(content2) if isinstance(content2, str) else content2
                    parsed2 = output_schema(**raw2)
                    return parsed2, total_usage, None, fetched_urls, raw_final_content
                except Exception as e2:
                    return None, total_usage, f"schema_mismatch after 2 attempts: {e2}", fetched_urls, raw_final_content

        # Dispatch tool calls
        # Append the assistant message with tool_calls first
        current_messages.append(message)

        tool_results = []
        for tc in tool_calls:
            if tool_call_count >= MAX_TOOL_CALLS:
                break
            tool_call_count += 1

            fn_name = tc.get("function", {}).get("name", "")
            fn_args = tc.get("function", {}).get("arguments", "{}")
            tc_id = tc.get("id", f"call_{tool_call_count}")

            result_str, url = _dispatch_tool(fn_name, fn_args, toolkit_names)

            if url:
                fetched_urls.add(url)
                meeseeks.fetched_urls.add(url)

            tool_results.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": result_str,
            })

        current_messages.extend(tool_results)

        if tool_call_count >= MAX_TOOL_CALLS:
            return None, total_usage, f"tool_call_limit_exceeded: {MAX_TOOL_CALLS} calls", fetched_urls, None


# ── Worker entry (unchanged interface, branched on toolkits) ─────────────

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

    Branching:
      meeseeks_cls.toolkits non-empty → _run_agent_loop (tool-using path)
      meeseeks_cls.toolkits empty     → parse_with_retry (existing path, unchanged)
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

        from meeseeks.contracts import MeeseeksResult
        start = time.monotonic()

        if meeseeks_cls.toolkits:
            # ── Tool-using path ───────────────────────────────────────────
            tools_spec = _build_tools_spec(meeseeks_cls.toolkits)
            parsed, usage, failure_reason, fetched_urls, raw_final = _run_agent_loop(
                meeseeks=meeseeks,
                messages=messages,
                provider=provider,
                tools_spec=tools_spec,
                toolkit_names=meeseeks_cls.toolkits,
                output_schema=meeseeks_cls.Output,
                timeout_seconds=meeseeks_cls.timeout_seconds,
            )
            duration_ms = int((time.monotonic() - start) * 1000)

            if parsed is None:
                result = MeeseeksResult.failure(
                    reason=failure_reason or "parse failed",
                    cost=usage,
                    raw_output=raw_final,
                )
                result = result.model_copy(update={"duration_ms": duration_ms})
            else:
                guard_failure = meeseeks.validate_output(parsed, fetched_urls)
                if guard_failure:
                    result = MeeseeksResult.failure(
                        reason=guard_failure,
                        partial=parsed.model_dump(),
                        cost=usage,
                        raw_output=json.dumps(parsed.model_dump()),
                    )
                    result = result.model_copy(update={"duration_ms": duration_ms})
                else:
                    result = MeeseeksResult.success(data=parsed, cost=usage, duration_ms=duration_ms)

        else:
            # ── No-toolkit path (fixture, thinkers) — unchanged ──────────
            from meeseeks.parser import StructuredOutputParser
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
            else:
                guard_failure = meeseeks.validate_output(parsed, meeseeks.fetched_urls)
                if guard_failure:
                    result = MeeseeksResult.failure(
                        reason=guard_failure,
                        partial=parsed.model_dump(),
                        cost=usage,
                    )
                    result = result.model_copy(update={"duration_ms": duration_ms})
                else:
                    result = MeeseeksResult.success(data=parsed, cost=usage, duration_ms=duration_ms)

        result_queue.put(result.model_dump())
    except Exception as e:
        from meeseeks.contracts import MeeseeksResult
        result = MeeseeksResult.failure(reason=f"worker exception: {e}")
        result_queue.put(result.model_dump())

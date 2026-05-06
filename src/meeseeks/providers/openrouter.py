from __future__ import annotations
import httpx
import json
import os
from meeseeks.contracts import TokenUsage
from meeseeks.providers.base import LLMProvider

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"


def _strip_markdown_fences(text: str) -> str:
    """Strip ```json ... ``` or ``` ... ``` wrappers that some models add."""
    import re
    stripped = text.strip()
    # Match ```json\n...\n``` or ```\n...\n```
    m = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", stripped, re.DOTALL)
    if m:
        return m.group(1).strip()
    return stripped

TIER_MODELS = {
    "thinker": [
        "anthropic/claude-haiku-4-5",          # claude-haiku-4-5 is the valid OR name
        "meta-llama/llama-3.1-70b-instruct",
        "google/gemini-flash-1.5",
    ],
    "worker": [
        "anthropic/claude-sonnet-4-5",
        "openai/gpt-4o",
        "deepseek/deepseek-chat",
    ],
    "heavy": [
        "anthropic/claude-opus-4",
        "openai/gpt-4-turbo",
    ],
}


class OpenRouterProvider(LLMProvider):
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ["OPENROUTER_API_KEY"]

    def chat(
        self,
        messages: list[dict],
        model: str,
        schema: type | None = None,
        timeout_seconds: int = 120,
    ) -> tuple[str | dict, TokenUsage]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body: dict = {"model": model, "messages": messages}
        if schema is not None:
            body["response_format"] = {"type": "json_object"}

        with httpx.Client(timeout=timeout_seconds) as client:
            resp = client.post(OPENROUTER_API_URL, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()

        usage = data.get("usage", {})
        cost_usd = float(data.get("usage", {}).get("cost", 0) or 0)
        token_usage = TokenUsage(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            cost_usd=cost_usd,
        )
        content = data["choices"][0]["message"]["content"]
        # Some models wrap JSON in markdown fences even with json_object mode — strip them
        if isinstance(content, str) and content.strip().startswith("```"):
            content = _strip_markdown_fences(content)
        if schema is not None:
            try:
                content = json.loads(content)
            except json.JSONDecodeError:
                pass  # caller handles

        return content, token_usage

    def chat_with_fallback(
        self,
        messages: list[dict],
        tier: str,
        schema: type | None = None,
        timeout_seconds: int = 120,
    ) -> tuple[str | dict, TokenUsage, str]:
        """Returns (content, usage, model_used). Tries tier's model chain."""
        models = TIER_MODELS.get(tier, TIER_MODELS["worker"])
        last_exc: Exception | None = None
        for model in models:
            try:
                content, usage = self.chat(messages, model, schema, timeout_seconds)
                return content, usage, model
            except (httpx.HTTPStatusError, httpx.TimeoutException) as e:
                last_exc = e
                continue
        raise RuntimeError(f"All models in tier '{tier}' failed. Last: {last_exc}")

    def chat_with_tools(
        self,
        messages: list[dict],
        model: str,
        tools: list[dict],
        timeout_seconds: int = 120,
    ) -> tuple[dict, TokenUsage]:
        """Single turn with tools. Returns the full message dict (may contain tool_calls).

        Response shape:
          {"role": "assistant", "content": str|None, "tool_calls": [...]}
        tool_calls items follow OpenAI format:
          {"id": "...", "type": "function", "function": {"name": "...", "arguments": "{...}"}}
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body: dict = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
        }
        with httpx.Client(timeout=timeout_seconds) as client:
            resp = client.post(OPENROUTER_API_URL, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()

        usage_raw = data.get("usage", {})
        token_usage = TokenUsage(
            prompt_tokens=usage_raw.get("prompt_tokens", 0),
            completion_tokens=usage_raw.get("completion_tokens", 0),
            total_tokens=usage_raw.get("total_tokens", 0),
            cost_usd=float(usage_raw.get("cost", 0) or 0),
        )
        message = data["choices"][0]["message"]
        return message, token_usage

    def chat_with_tools_fallback(
        self,
        messages: list[dict],
        tier: str,
        tools: list[dict],
        timeout_seconds: int = 120,
    ) -> tuple[dict, TokenUsage, str]:
        """Returns (message, usage, model_used). Tries tier's model chain."""
        models = TIER_MODELS.get(tier, TIER_MODELS["worker"])
        last_exc: Exception | None = None
        for model in models:
            try:
                message, usage = self.chat_with_tools(messages, model, tools, timeout_seconds)
                return message, usage, model
            except (httpx.HTTPStatusError, httpx.TimeoutException) as e:
                last_exc = e
                continue
        raise RuntimeError(f"All models in tier '{tier}' failed (tools). Last: {last_exc}")

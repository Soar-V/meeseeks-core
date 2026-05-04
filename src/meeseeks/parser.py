from __future__ import annotations
import json
from pydantic import BaseModel, ValidationError
from meeseeks.contracts import TokenUsage


class StructuredOutputParser:
    """§4.4: try parse → retry with validation error → structured failure.

    Extracted from contracts.py for module clarity.
    """

    def __init__(self, schema: type[BaseModel], provider, tier: str = "worker"):
        self.schema = schema
        self.provider = provider
        self.tier = tier  # use the meeseeks's actual tier, not always "worker"

    def parse_with_retry(
        self, messages: list[dict], timeout_seconds: int = 120
    ) -> tuple[BaseModel | None, TokenUsage, str | None]:
        """
        Returns (parsed_output, total_usage, failure_reason).
        failure_reason is None on success.
        """
        total_usage = TokenUsage()

        # Attempt 1
        content, usage, _ = self.provider.chat_with_fallback(
            messages, tier=self.tier, schema=self.schema, timeout_seconds=timeout_seconds
        )
        total_usage.prompt_tokens += usage.prompt_tokens
        total_usage.completion_tokens += usage.completion_tokens
        total_usage.total_tokens += usage.total_tokens
        total_usage.cost_usd += usage.cost_usd

        parsed, err = self._try_parse(content)
        if parsed:
            return parsed, total_usage, None

        # Attempt 2 — retry with validation error injected as a new user message
        assistant_content = json.dumps(content) if isinstance(content, dict) else str(content)
        retry_messages = messages + [
            {"role": "assistant", "content": assistant_content},
            {"role": "user", "content": (
                f"Your output failed schema validation: {err}\n"
                "Fix it and return valid JSON matching the required schema. No preamble, no explanation."
            )},
        ]
        content2, usage2, _ = self.provider.chat_with_fallback(
            retry_messages, tier=self.tier, schema=self.schema, timeout_seconds=timeout_seconds
        )
        total_usage.prompt_tokens += usage2.prompt_tokens
        total_usage.completion_tokens += usage2.completion_tokens
        total_usage.total_tokens += usage2.total_tokens
        total_usage.cost_usd += usage2.cost_usd

        parsed2, err2 = self._try_parse(content2)
        if parsed2:
            return parsed2, total_usage, None

        return None, total_usage, f"schema_mismatch after 2 attempts: {err2}"

    def _try_parse(self, content) -> tuple[BaseModel | None, str | None]:
        if isinstance(content, dict):
            raw = content
        else:
            try:
                raw = json.loads(content)
            except (json.JSONDecodeError, TypeError) as e:
                return None, f"JSON parse error: {e}"
        try:
            return self.schema(**raw), None
        except ValidationError as e:
            return None, str(e)

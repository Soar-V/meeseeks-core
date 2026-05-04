from abc import ABC, abstractmethod
from meeseeks.contracts import TokenUsage


class LLMProvider(ABC):
    @abstractmethod
    def chat(
        self,
        messages: list[dict],
        model: str,
        schema: type | None = None,
        timeout_seconds: int = 120,
    ) -> tuple[str | dict, TokenUsage]:
        """
        Returns (raw_content, token_usage).
        raw_content is str for plain chat, dict for structured output.
        """
        ...

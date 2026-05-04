from __future__ import annotations
from typing import Literal, ClassVar
from pydantic import BaseModel

_REGISTRY: dict[str, type["Meeseeks"]] = {}


def register_meeseeks(cls):
    """Decorator: adds meeseeks class to global registry."""
    _REGISTRY[cls.name] = cls
    return cls


def get_registry() -> dict[str, type["Meeseeks"]]:
    return dict(_REGISTRY)


class Meeseeks:
    """Base class for all meeseeks. Subclass and decorate with @register_meeseeks."""

    name: ClassVar[str]
    description: ClassVar[str]
    triggers: ClassVar[list[str]] = []

    tier: ClassVar[Literal["thinker", "worker", "heavy"]] = "worker"
    toolkits: ClassVar[list[str]] = []
    isolation: ClassVar[Literal["inline", "subprocess"]] = "subprocess"

    estimated_cost_usd: ClassVar[float] = 0.10
    timeout_seconds: ClassVar[int] = 120
    destructive: ClassVar[bool] = False
    use_framework: ClassVar[bool] = True

    class Input(BaseModel):
        pass

    class Output(BaseModel):
        pass

    def system_prompt(self, inputs: "Meeseeks.Input") -> str:
        raise NotImplementedError

    def format(self, output: "Meeseeks.Output") -> str:
        """How Hermes renders this result for Discord."""
        return str(output.model_dump())

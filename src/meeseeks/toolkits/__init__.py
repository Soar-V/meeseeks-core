from __future__ import annotations

TOOLKIT_REGISTRY: dict[str, type] = {}


def register_toolkit(cls):
    """Decorator: adds toolkit class to global registry."""
    TOOLKIT_REGISTRY[cls.name] = cls
    return cls

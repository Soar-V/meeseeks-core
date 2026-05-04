from pydantic import BaseModel
from meeseeks.registry import register_meeseeks, get_registry, Meeseeks


@register_meeseeks
class EchoMeeseeks(Meeseeks):
    name = "echo"
    description = "Echoes input"
    tier = "thinker"

    class Input(BaseModel):
        message: str

    class Output(BaseModel):
        echo: str

    def system_prompt(self, inputs):
        return f"Echo back: {inputs.message}"

    def format(self, output):
        return output.echo


def test_registration():
    registry = get_registry()
    assert "echo" in registry
    assert registry["echo"] is EchoMeeseeks


def test_meeseeks_class_vars():
    assert EchoMeeseeks.tier == "thinker"
    assert EchoMeeseeks.destructive is False
    assert EchoMeeseeks.use_framework is True

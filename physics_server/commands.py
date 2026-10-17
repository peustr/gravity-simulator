"""Validate the complete UDP command before it can mutate the simulation."""
import math

import world as W

COMMANDS = {
    "hello": "heartbeat (send twice per second)",
    "bye": "disconnect",
    "add": "type, pos, mode (orbit/launch), drag, mass_mult",
    "predict": "same as add, plus req",
    "belt": "pos, count, mass_mult",
    "remove": "id",
    "supernova": "id",
    "pause": "value (boolean; omit to toggle)",
    "speed": "value (clamped to 0.05–2000)",
    "clear": "no fields",
    "preset": "name",
}


def number(value, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"Expected a finite number in [{low}, {high}]")
    return value


def integer(value, low=0, high=16_000_000):
    number(value, low, high)
    if type(value) is not int:
        raise ValueError("Expected an integer")


def vector(value):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError("Expected a three-component vector")
    for component in value:
        number(component, -1e6, 1e6)


def validate(msg):
    cmd = msg.get("cmd")
    if not isinstance(cmd, str) or cmd not in COMMANDS:
        raise ValueError("Unknown command")
    if cmd in ("add", "predict", "belt"):
        vector(msg.get("pos"))
        number(msg.get("mass_mult", 1.0), 1e-6, 1e6)
    if cmd in ("add", "predict"):
        kind = msg.get("type")
        if not isinstance(kind, str) or kind not in W.TYPE_KEYS:
            raise ValueError("Unknown body type")
        if msg.get("mode", "orbit") not in ("orbit", "launch"):
            raise ValueError("Unknown placement mode")
        vector(msg.get("drag", (0, 0, 0)))
    if cmd == "predict":
        integer(msg.get("req", 0))
    elif cmd == "belt":
        integer(msg.get("count", 60), 1, W.MAX_BODIES)
    elif cmd in ("remove", "supernova"):
        integer(msg.get("id"), 1)
    elif cmd == "pause" and "value" in msg and type(msg["value"]) is not bool:
        raise ValueError("Pause value must be a boolean")
    elif cmd == "speed":
        number(msg.get("value", 10.0), -1e6, 1e6)
    elif cmd == "preset" and msg.get("name", "empty") not in W.SCENARIOS:
        raise ValueError("Unknown scenario")

#!/usr/bin/env python3
"""Shared Quest UDP teleop packet decode/format (used by udp_datalog and quest_teleop)."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

GRIP_BUTTON_THRESHOLD = 0.5


@dataclass
class HandCommand:
    x: float
    y: float
    trigger: float
    grip: float
    grip_button: bool
    primary_button: bool
    secondary_button: bool


@dataclass
class TeleopCommand:
    session: str
    sequence: int
    enabled: bool
    left: HandCommand
    right: HandCommand

    @property
    def trigger(self) -> float:
        """Backward-compatible alias for the right index trigger."""
        return self.right.trigger


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def finite_float(
    payload: dict[str, Any],
    key: str,
    default: float = 0.0,
) -> float:
    value = float(payload.get(key, default))

    if not math.isfinite(value):
        raise ValueError(f"{key} must be finite")

    return value


def parse_bool(value: Any, default: bool = False) -> bool:
    """Parse JSON booleans that may arrive as bool, 0/1, or strings."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return default


def decode_enabled(payload: dict[str, Any]) -> bool:
    """Read the Quest app's explicit teleop-armed flag (often always false)."""
    if "enabled" not in payload:
        return False
    return parse_bool(payload["enabled"])


def finite_bool(
    payload: dict[str, Any],
    key: str,
    default: bool = False,
) -> bool:
    if key not in payload:
        return default

    return parse_bool(payload[key], default=default)


def decode_hand(
    payload: dict[str, Any],
    prefix: str,
    legacy_x: float,
    legacy_y: float,
    legacy_trigger: float | None = None,
) -> HandCommand:
    trigger_key = f"{prefix}_trigger"
    if legacy_trigger is not None and trigger_key not in payload:
        trigger = legacy_trigger
    else:
        trigger = finite_float(payload, trigger_key)

    grip = clamp(finite_float(payload, f"{prefix}_grip"), 0.0, 1.0)
    grip_button = finite_bool(payload, f"{prefix}_grip_button")
    if not grip_button and grip >= GRIP_BUTTON_THRESHOLD:
        grip_button = True

    return HandCommand(
        x=clamp(finite_float(payload, f"{prefix}_x", legacy_x), -1.0, 1.0),
        y=clamp(finite_float(payload, f"{prefix}_y", legacy_y), -1.0, 1.0),
        trigger=clamp(trigger, 0.0, 1.0),
        grip=grip,
        grip_button=grip_button,
        primary_button=finite_bool(payload, f"{prefix}_primary_button"),
        secondary_button=finite_bool(payload, f"{prefix}_secondary_button"),
    )


def decode_command(packet: bytes) -> TeleopCommand:
    if len(packet) > 2048:
        raise ValueError("Packet is too large")

    payload = json.loads(packet.decode("utf-8"))

    session = str(payload.get("session", ""))

    if not session or len(session) > 64:
        raise ValueError("Invalid session")

    left_x = finite_float(payload, "left_x")
    left_y = finite_float(payload, "left_y")
    right_x = finite_float(payload, "right_x")
    right_y = finite_float(payload, "right_y")
    legacy_trigger = finite_float(payload, "trigger")

    return TeleopCommand(
        session=session,
        sequence=int(payload.get("sequence", -1)),
        enabled=decode_enabled(payload),
        left=decode_hand(payload, "left", left_x, left_y),
        right=decode_hand(payload, "right", right_x, right_y, legacy_trigger),
    )


def format_hand(name: str, hand: HandCommand) -> str:
    buttons = []
    if hand.primary_button:
        buttons.append("primary")
    if hand.secondary_button:
        buttons.append("secondary")
    if hand.grip_button:
        buttons.append("grip")

    button_text = ",".join(buttons) if buttons else "none"

    return (
        f"{name}=({hand.x:+.3f}, {hand.y:+.3f}) "
        f"trigger={hand.trigger:.3f} grip={hand.grip:.3f} "
        f"buttons={button_text}"
    )


def format_command(command: TeleopCommand) -> str:
    return (
        f"session={command.session!r} seq={command.sequence} "
        f"enabled={command.enabled} "
        f"{format_hand('left', command.left)} "
        f"{format_hand('right', command.right)}"
    )

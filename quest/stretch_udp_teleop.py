#!/usr/bin/env python3

from __future__ import annotations

import json
import math
import signal
import socket
import sys
import time
from dataclasses import dataclass
from typing import Any

LISTEN_ADDRESS = "0.0.0.0"
LISTEN_PORT = 5005

SOCKET_POLL_TIMEOUT_SECONDS = 0.02


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


def finite_bool(
    payload: dict[str, Any],
    key: str,
    default: bool = False,
) -> bool:
    if key not in payload:
        return default

    return bool(payload[key])


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

    return HandCommand(
        x=clamp(finite_float(payload, f"{prefix}_x", legacy_x), -1.0, 1.0),
        y=clamp(finite_float(payload, f"{prefix}_y", legacy_y), -1.0, 1.0),
        trigger=clamp(trigger, 0.0, 1.0),
        grip=clamp(finite_float(payload, f"{prefix}_grip"), 0.0, 1.0),
        grip_button=finite_bool(payload, f"{prefix}_grip_button"),
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
        enabled=bool(payload.get("enabled", False)),
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


class StretchTeleop:
    def __init__(self) -> None:
        self.socket = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM,
        )

        # Allow a quick restart after stopping the program.
        self.socket.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_REUSEADDR,
            1,
        )

        self.running = True
        self.packet_count = 0

    def start(self) -> None:
        self.socket.bind((LISTEN_ADDRESS, LISTEN_PORT))
        self.socket.settimeout(SOCKET_POLL_TIMEOUT_SECONDS)

        print(
            f"Listening on UDP {LISTEN_ADDRESS}:{LISTEN_PORT} "
            "(print-only mode, robot not controlled)",
            flush=True,
        )

    def print_packet(
        self,
        packet: bytes,
        sender: tuple[str, int],
    ) -> None:
        self.packet_count += 1
        timestamp = time.strftime("%H:%M:%S")

        try:
            command = decode_command(packet)
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ) as exception:
            print(
                f"[{timestamp}] #{self.packet_count} from {sender[0]}:{sender[1]} "
                f"raw={packet!r} (decode failed: {exception})",
                flush=True,
            )
            return

        print(
            f"[{timestamp}] #{self.packet_count} from {sender[0]}:{sender[1]} "
            f"session={command.session!r} seq={command.sequence} "
            f"enabled={command.enabled} "
            f"{format_hand('left', command.left)} "
            f"{format_hand('right', command.right)}",
            flush=True,
        )

    def run(self) -> None:
        while self.running:
            try:
                packet, sender = self.socket.recvfrom(2048)
                self.print_packet(packet, sender)

            except socket.timeout:
                pass

            except OSError as exception:
                if self.running:
                    print(
                        f"Socket error: {exception}",
                        file=sys.stderr,
                        flush=True,
                    )

    def shutdown(self) -> None:
        if not self.running:
            return

        self.running = False
        self.socket.close()


def main() -> None:
    teleop = StretchTeleop()

    def handle_signal(
        _signal_number: int,
        _frame: Any,
    ) -> None:
        teleop.shutdown()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        teleop.start()
        teleop.run()
    finally:
        teleop.shutdown()


if __name__ == "__main__":
    main()

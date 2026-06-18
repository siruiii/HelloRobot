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
class TeleopCommand:
    session: str
    sequence: int
    enabled: bool

    left_x: float
    left_y: float
    right_x: float
    right_y: float
    trigger: float


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


def decode_command(packet: bytes) -> TeleopCommand:
    if len(packet) > 2048:
        raise ValueError("Packet is too large")

    payload = json.loads(packet.decode("utf-8"))

    session = str(payload.get("session", ""))

    if not session or len(session) > 64:
        raise ValueError("Invalid session")

    return TeleopCommand(
        session=session,
        sequence=int(payload.get("sequence", -1)),
        enabled=bool(payload.get("enabled", False)),
        left_x=clamp(finite_float(payload, "left_x"), -1.0, 1.0),
        left_y=clamp(finite_float(payload, "left_y"), -1.0, 1.0),
        right_x=clamp(finite_float(payload, "right_x"), -1.0, 1.0),
        right_y=clamp(finite_float(payload, "right_y"), -1.0, 1.0),
        trigger=clamp(finite_float(payload, "trigger"), 0.0, 1.0),
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
            f"left=({command.left_x:+.3f}, {command.left_y:+.3f}) "
            f"right=({command.right_x:+.3f}, {command.right_y:+.3f}) "
            f"trigger={command.trigger:.3f}",
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

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

import stretch_body.robot


LISTEN_ADDRESS = "0.0.0.0"
LISTEN_PORT = 5005

WATCHDOG_TIMEOUT_SECONDS = 0.25
SOCKET_POLL_TIMEOUT_SECONDS = 0.02

MAX_LINEAR_VELOCITY = 0.08   # meters/second
MAX_ANGULAR_VELOCITY = 0.30  # radians/second


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
        self.robot = stretch_body.robot.Robot()

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
        self.motion_active = False

        self.active_session: str | None = None
        self.last_sequence = -1
        self.last_packet_time = 0.0
        self.last_sender: tuple[str, int] | None = None

    def start(self) -> None:
        if not self.robot.startup():
            raise RuntimeError("Could not start Stretch hardware")

        # Newer Stretch Body versions use is_homed().
        if hasattr(self.robot, "is_homed"):
            if not self.robot.is_homed():
                raise RuntimeError(
                    "Stretch is not homed. Home it before teleoperation."
                )
        elif hasattr(self.robot, "is_calibrated"):
            if not self.robot.is_calibrated():
                raise RuntimeError(
                    "Stretch is not calibrated/homed."
                )

        self.socket.bind((LISTEN_ADDRESS, LISTEN_PORT))
        self.socket.settimeout(SOCKET_POLL_TIMEOUT_SECONDS)

        print(
            f"Listening on UDP {LISTEN_ADDRESS}:{LISTEN_PORT}",
            flush=True,
        )

    def stop_base(self) -> None:
        self.robot.base.set_velocity(0.0, 0.0)
        self.robot.push_command()

        if self.motion_active:
            print("Base stopped", flush=True)

        self.motion_active = False

    def apply_command(self, command: TeleopCommand) -> None:
        if not command.enabled:
            self.stop_base()
            return

        linear_velocity = (
            command.left_y * MAX_LINEAR_VELOCITY
        )

        angular_velocity = (
            -command.left_x * MAX_ANGULAR_VELOCITY
        )

        self.robot.base.set_velocity(
            linear_velocity,
            angular_velocity,
        )
        self.robot.push_command()

        self.motion_active = (
            abs(linear_velocity) > 0.001
            or abs(angular_velocity) > 0.001
        )

        # The remaining controller values are available here:
        #
        # command.right_x
        # command.right_y
        # command.trigger
        #
        # Add arm, lift, and gripper control only after the
        # base and watchdog have been tested thoroughly.

    def accept_sequence(self, command: TeleopCommand) -> bool:
        # A new Unity launch creates a new session ID, so its
        # sequence counter may safely restart from zero.
        if command.session != self.active_session:
            print(
                f"New controller session: {command.session}",
                flush=True,
            )

            self.stop_base()
            self.active_session = command.session
            self.last_sequence = -1

        if command.sequence <= self.last_sequence:
            return False

        self.last_sequence = command.sequence
        return True

    def check_watchdog(self) -> None:
        if self.last_packet_time == 0.0:
            return

        packet_age = time.monotonic() - self.last_packet_time

        if packet_age > WATCHDOG_TIMEOUT_SECONDS:
            self.stop_base()

            # Reset so that the timeout is not printed continuously.
            self.last_packet_time = 0.0

            print(
                "Watchdog timeout: controller stream lost",
                flush=True,
            )

    def run(self) -> None:
        while self.running:
            try:
                packet, sender = self.socket.recvfrom(2048)

                command = decode_command(packet)

                if not self.accept_sequence(command):
                    continue

                self.last_sender = sender
                self.last_packet_time = time.monotonic()

                self.apply_command(command)

            except socket.timeout:
                pass

            except (
                UnicodeDecodeError,
                json.JSONDecodeError,
                TypeError,
                ValueError,
            ) as exception:
                print(
                    f"Rejected packet: {exception}",
                    file=sys.stderr,
                    flush=True,
                )

            except OSError as exception:
                if self.running:
                    print(
                        f"Socket error: {exception}",
                        file=sys.stderr,
                        flush=True,
                    )

            self.check_watchdog()

    def shutdown(self) -> None:
        if not self.running:
            return

        self.running = False

        try:
            self.stop_base()
        except Exception as exception:
            print(
                f"Could not stop base cleanly: {exception}",
                file=sys.stderr,
            )

        try:
            self.socket.close()
        finally:
            self.robot.stop()


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
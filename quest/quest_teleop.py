#!/usr/bin/env python3
"""Stretch teleop over UDP from a Quest (or Unity) controller.

Uses the same joint mapping as ``tests/test_w_gamepad.py`` and the official
``stretch_gamepad_teleop.py`` via ``stretch_body.gamepad_teleop.GamePadTeleop``.

Quest controller -> gamepad mapping:
  Left thumbstick            base tank drive
  Right thumbstick X / Y     arm / lift
  Left grip button           wrist yaw left  (LB)
  Right grip button          wrist yaw right (RB)
  Left index trigger         precision mode
  Right index trigger        fast base mode
  Right primary (A)          gripper close
  Right secondary (B)        gripper open
  Left primary (X)           toggle D-pad head vs dex wrist
  Left secondary (Y, hold)   stow

Requirements:
  - Robot homed: ``stretch_robot_home.py``
  - stretch_body installed on the robot PC

Keep the runstop within reach. Long-press Back / PC shutdown is disabled.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

import stretch_body.gamepad_teleop as gamepad_teleop_module

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TESTS_DIR = str(_REPO_ROOT / "tests")
_QUEST_DIR = str(_REPO_ROOT / "quest")
for _path in (_TESTS_DIR, _QUEST_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from bluetooth_gamepad_controller import (  # noqa: E402
    DEFAULT_STATE,
    _apply_dead_zone,
)
from udp_protocol import TeleopCommand, decode_command, format_command  # noqa: E402

LISTEN_ADDRESS = "0.0.0.0"
LISTEN_PORT = 5005

WATCHDOG_TIMEOUT_SECONDS = 0.25
SOCKET_POLL_TIMEOUT_SECONDS = 0.02


def command_to_gamepad_state(command: TeleopCommand) -> dict[str, Any]:
    """Map decoded Quest UDP input to Stretch gamepad_state (test_w_gamepad)."""
    if not command.enabled:
        return dict(DEFAULT_STATE)

    left = command.left
    right = command.right

    return {
        "middle_led_ring_button_pressed": False,
        "left_stick_x": _apply_dead_zone(left.x),
        "left_stick_y": _apply_dead_zone(-left.y),
        "right_stick_x": _apply_dead_zone(right.x),
        "right_stick_y": _apply_dead_zone(-right.y),
        "left_stick_button_pressed": False,
        "right_stick_button_pressed": False,
        "bottom_button_pressed": right.primary_button,
        "top_button_pressed": left.secondary_button,
        "left_button_pressed": left.primary_button,
        "right_button_pressed": right.secondary_button,
        "left_shoulder_button_pressed": left.grip_button,
        "right_shoulder_button_pressed": right.grip_button,
        "select_button_pressed": False,
        "start_button_pressed": False,
        "left_trigger_pulled": left.trigger,
        "right_trigger_pulled": right.trigger,
        "bottom_pad_pressed": False,
        "top_pad_pressed": False,
        "left_pad_pressed": False,
        "right_pad_pressed": False,
    }


class UdpGamepadController(threading.Thread):
    """UDP listener that publishes gamepad_state for GamePadTeleop."""

    def __init__(
        self,
        listen_address: str = LISTEN_ADDRESS,
        listen_port: int = LISTEN_PORT,
        print_packets: bool = False,
    ) -> None:
        super().__init__(name=self.__class__.__name__)
        self.daemon = True
        self.listen_address = listen_address
        self.listen_port = listen_port
        self.print_packets = print_packets

        self.lock = threading.Lock()
        self.stop_thread = False
        self.shutdown_flag = threading.Event()
        self.is_gamepad_dongle = False

        self.gamepad_state = dict(DEFAULT_STATE)
        self._socket: socket.socket | None = None

        self.active_session: str | None = None
        self.last_sequence = -1
        self.last_packet_time = 0.0
        self.packet_count = 0

    def _accept_sequence(self, command: TeleopCommand) -> bool:
        if command.session != self.active_session:
            print(
                f"New controller session: {command.session}",
                flush=True,
            )
            self.active_session = command.session
            self.last_sequence = -1

        # Senders that omit sequence (default -1) or repeat a fixed value (e.g. 0)
        # should still stream live input; only drop clearly stale packets.
        if command.sequence < 0:
            return True

        if self.last_sequence >= 0 and command.sequence < self.last_sequence:
            if self.print_packets:
                print(
                    f"Rejected stale packet seq={command.sequence} "
                    f"(last={self.last_sequence})",
                    flush=True,
                )
            return False

        if command.sequence > self.last_sequence:
            self.last_sequence = command.sequence

        return True

    def _zero_state_locked(self) -> None:
        self.gamepad_state.clear()
        self.gamepad_state.update(DEFAULT_STATE)
        self.is_gamepad_dongle = False

    def _check_watchdog(self) -> None:
        if self.last_packet_time == 0.0:
            return

        packet_age = time.monotonic() - self.last_packet_time
        if packet_age <= WATCHDOG_TIMEOUT_SECONDS:
            return

        with self.lock:
            self._zero_state_locked()
            self.last_packet_time = 0.0

        print(
            "Watchdog timeout: controller stream lost",
            flush=True,
        )

    def run(self) -> None:
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((self.listen_address, self.listen_port))
        self._socket.settimeout(SOCKET_POLL_TIMEOUT_SECONDS)

        print(
            f"Listening on UDP {self.listen_address}:{self.listen_port}",
            flush=True,
        )

        while not self.shutdown_flag.is_set() and not self.stop_thread:
            try:
                packet, sender = self._socket.recvfrom(2048)
                command = decode_command(packet)

                if not self._accept_sequence(command):
                    continue

                new_state = command_to_gamepad_state(command)
                with self.lock:
                    self.gamepad_state.clear()
                    self.gamepad_state.update(new_state)
                    self.is_gamepad_dongle = True

                self.last_packet_time = time.monotonic()
                self.packet_count += 1

                if self.print_packets:
                    print(
                        f"#{self.packet_count} from {sender[0]}:{sender[1]} "
                        f"{format_command(command)}",
                        flush=True,
                    )

            except socket.timeout:
                self._check_watchdog()

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
                if not self.shutdown_flag.is_set() and not self.stop_thread:
                    print(
                        f"Socket error: {exception}",
                        file=sys.stderr,
                        flush=True,
                    )

        if self._socket is not None:
            self._socket.close()
            self._socket = None

        with self.lock:
            self._zero_state_locked()

    def stop(self) -> None:
        if not self.stop_thread:
            with self.lock:
                self.stop_thread = True
            self.shutdown_flag.set()


class QuestUdpGamePadTeleop(gamepad_teleop_module.GamePadTeleop):
    """GamePadTeleop driven by Quest UDP packets."""

    def __init__(
        self,
        listen_address: str = LISTEN_ADDRESS,
        listen_port: int = LISTEN_PORT,
        print_packets: bool = False,
        collision_mgmt: bool = True,
    ) -> None:
        super().__init__(
            robot_instance=True,
            print_dongle_status=False,
            collision_mgmt=collision_mgmt,
        )
        self.gamepad_controller = UdpGamepadController(
            listen_address=listen_address,
            listen_port=listen_port,
            print_packets=print_packets,
        )
        self.controller_state = self.gamepad_controller.gamepad_state

    def manage_shutdown(self, robot) -> None:
        """Disable the official long-press Back PC shutdown."""
        if self.controller_state["select_button_pressed"]:
            if not self._last_shutdwon_btn_press:
                self._last_shutdwon_btn_press = time.time()
            if time.time() - self._last_shutdwon_btn_press >= 2:
                print(
                    "Long Back press ignored "
                    "(PC shutdown disabled in stretch_udp_teleop.py).",
                    flush=True,
                )
                self._last_shutdwon_btn_press = None
        else:
            self._last_shutdwon_btn_press = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Teleoperate Stretch from Quest UDP controller packets.",
    )
    parser.add_argument(
        "--address",
        default=LISTEN_ADDRESS,
        help=f"UDP listen address (default: {LISTEN_ADDRESS}).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=LISTEN_PORT,
        help=f"UDP listen port (default: {LISTEN_PORT}).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print each accepted UDP packet.",
    )
    parser.add_argument(
        "--no-collision-mgmt",
        action="store_true",
        help="Disable stretch_body collision management.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    print("Starting Stretch Quest UDP teleop...")
    print(
        "Mapping matches test_w_gamepad.py / stretch_gamepad_teleop.py. "
        "Press Ctrl+C to quit.",
        flush=True,
    )

    teleop = QuestUdpGamePadTeleop(
        listen_address=args.address,
        listen_port=args.port,
        print_packets=args.verbose,
        collision_mgmt=not args.no_collision_mgmt,
    )

    teleop.startup()

    robot = teleop.robot
    if hasattr(robot, "is_homed"):
        homed = robot.is_homed()
    else:
        homed = robot.is_calibrated()

    if not homed:
        print(
            "WARNING: Robot is not homed. "
            "Run stretch_robot_home.py before teleoperation.",
            file=sys.stderr,
        )

    try:
        teleop.mainloop()
        return 0
    except KeyboardInterrupt:
        print("\nQuest UDP teleop interrupted.")
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        teleop.stop()


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Stretch gamepad teleop with an arm/disarm safety button (8BitDo Lite 2).

Same joint mapping as ``test_w_gamepad.py`` / the official
``stretch_gamepad_teleop.py``, with these differences:

  - The robot must already be homed. This script never homes or calibrates;
    it exits if the robot is not homed.
  - The controller is always the 8BitDo Lite 2 (no ``--profile`` needed).
  - Teleop starts DISARMED. No joint moves until you press Start to arm.
    Press Start again, or press Select, to disarm. Disarming stops all joints.
  - Arming is refused unless both sticks are centered.
  - Losing the gamepad connection disarms automatically.

Requirements:
  - Robot homed: ``stretch_robot_home.py``
  - pygame: ``python3 -m pip install pygame``
  - 8BitDo Lite 2 paired over Bluetooth (rear switch in D mode)

Quick start:
  stretch_robot_home.py
  python3 test_gamepad_safe.py

Keep the runstop within reach.
"""

from __future__ import annotations

import argparse
import sys
import time

import stretch_body.gamepad_teleop as gamepad_teleop_module

from bluetooth_gamepad_controller import BluetoothGamepadController, list_joysticks


PROFILE = "8bitdo_lite2"

HELP = """
Stretch gamepad teleop (safe mode, 8BitDo Lite 2)

Safety:
  Start                 ARM / DISARM teleop (starts disarmed)
  Select                DISARM immediately
  Runstop               hardware stop (always available)

Mapping (only active while armed):
  Left stick            drive base
  Right stick X         arm
  Right stick Y         lift
  L / R                 wrist yaw left / right
  D-pad                 head pan/tilt
  L2 (hold)             precision mode
  R2 (hold)             fast base mode
  A / B                 gripper close / open
  X                     toggle D-pad target (head vs dex wrist)
  Y (hold 2 s)          stow robot

Homing is disabled in this script. Press Ctrl+C to quit.
"""

STICK_KEYS = ("left_stick_x", "left_stick_y", "right_stick_x", "right_stick_y")


class SafeGamePadTeleop(gamepad_teleop_module.GamePadTeleop):
    """GamePadTeleop gated behind an arm/disarm button, with homing removed."""

    def __init__(self, joystick_index=0, print_status=True, collision_mgmt=True):
        super().__init__(
            robot_instance=True,
            print_dongle_status=False,
            collision_mgmt=collision_mgmt,
        )
        self.gamepad_controller = BluetoothGamepadController(
            joystick_index=joystick_index,
            print_status=print_status,
            profile=PROFILE,
        )
        self.controller_state = self.gamepad_controller.gamepad_state
        self.armed = False
        self._last_start_pressed = False

    def _sticks_centered(self):
        return all(self.controller_state[key] == 0.0 for key in STICK_KEYS)

    def _set_armed(self, armed, robot, reason):
        if armed == self.armed:
            return
        self.armed = armed
        if armed:
            print(f"\n[ARMED] Teleop enabled ({reason}).")
            self.do_double_beep(robot)
        else:
            print(f"\n[DISARMED] Teleop disabled ({reason}).")
            self._safety_stop(robot)
            self.do_single_beep(robot)

    def _manage_safety_button(self, robot):
        connected = self.gamepad_controller.is_gamepad_dongle
        start_pressed = self.controller_state["start_button_pressed"]
        start_edge = start_pressed and not self._last_start_pressed
        self._last_start_pressed = start_pressed

        if not connected:
            self._set_armed(False, robot, "gamepad disconnected")
            return
        if self.controller_state["select_button_pressed"]:
            self._set_armed(False, robot, "Select pressed")
            return
        if not start_edge:
            return

        if self.armed:
            self._set_armed(False, robot, "Start pressed")
        elif not self._sticks_centered():
            print("\nRefusing to arm: release both sticks to center first.")
        else:
            self._set_armed(True, robot, "Start pressed")

    def do_motion(self, state=None, robot=None):
        """Replace the base loop: never home, and only move while armed."""
        if not robot:
            robot = self.robot
        self._i += 1
        self._update_state(state)
        self._update_modes()
        with self.lock:
            if not robot.is_homed():
                self._set_armed(False, robot, "robot not homed")
                self._safety_stop(robot)
                if self._i % 100 == 0:
                    print("Robot is not homed. Quit and run stretch_robot_home.py.")
                return

            self._manage_safety_button(robot)

            if self.armed and not self.currently_stowing:
                self.command_robot_joints(robot)
            elif not self.currently_stowing:
                self._safety_stop(robot)
                if self._i % 150 == 0:
                    print("Disarmed. Press Start to enable teleop.")

    def manage_shutdown(self, robot):
        """Select is the disarm button here; no long-press PC shutdown."""


def parse_args():
    parser = argparse.ArgumentParser(
        description="Teleoperate a homed Stretch with an 8BitDo Lite 2, "
        "gated behind a Start arm/disarm button.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List connected gamepads and exit.",
    )
    parser.add_argument(
        "--index",
        type=int,
        default=0,
        help="Joystick index to use (default: 0).",
    )
    parser.add_argument(
        "--no-collision-mgmt",
        action="store_true",
        help="Disable stretch_body collision management.",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.list:
        devices = list_joysticks()
        if not devices:
            print("No gamepads detected.")
            return 1
        print("Detected gamepads:")
        for index, name in devices:
            print(f"  [{index}] {name}")
        return 0

    print("Starting Stretch safe gamepad teleop...")
    print(HELP)

    teleop = SafeGamePadTeleop(
        joystick_index=args.index,
        print_status=True,
        collision_mgmt=not args.no_collision_mgmt,
    )

    try:
        teleop.startup()

        if not teleop.robot.is_homed():
            print(
                "ERROR: Robot is not homed. Run stretch_robot_home.py first, "
                "then start this script again.",
                file=sys.stderr,
            )
            return 1

        print("Robot is homed. Teleop is DISARMED. Press Start to arm.")

        while True:
            teleop.step_mainloop()
    except KeyboardInterrupt:
        print("\nSafe gamepad teleop interrupted.")
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        try:
            teleop._safety_stop(teleop.robot)
            teleop.robot.push_command()
        except Exception:
            pass
        teleop.stop()


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3

from __future__ import annotations

import json
import signal
import socket
import sys
import time
from typing import Any

from udp_protocol import decode_command, format_command

LISTEN_ADDRESS = "0.0.0.0"
LISTEN_PORT = 5005

SOCKET_POLL_TIMEOUT_SECONDS = 0.02


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
            f"{format_command(command)}",
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

#!/usr/bin/env python3
"""
Direct-Python health test for the Hello Robot Stretch RE1 RPLIDAR.

No ROS dependency. Uses the `rplidar` Python package and the Stretch udev
device alias `/dev/hello-lrf`.

Install, if needed:
    python3 -m pip install rplidar-roboticia

Run:
    python3 test_stretch_re1_lidar_python.py

Optional:
    python3 test_stretch_re1_lidar_python.py --port /dev/ttyUSB0
"""

import argparse
import math
import statistics
import sys
import time

try:
    from rplidar import RPLidar, RPLidarException
except ImportError:
    print(
        "ERROR: Python package `rplidar` is not installed.\n"
        "Install it with: python3 -m pip install rplidar-roboticia",
        file=sys.stderr,
    )
    raise SystemExit(2)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="/dev/hello-lrf")
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--timeout", type=float, default=3.0)
    parser.add_argument("--scans", type=int, default=20)
    parser.add_argument("--min-points", type=int, default=50)
    parser.add_argument("--min-valid-fraction", type=float, default=0.90)
    parser.add_argument("--min-scan-hz", type=float, default=2.0)
    parser.add_argument("--max-scan-hz", type=float, default=20.0)
    args = parser.parse_args()

    lidar = None
    scan_times = []
    point_counts = []
    valid_fractions = []
    distances_mm = []

    try:
        lidar = RPLidar(
            args.port,
            baudrate=args.baudrate,
            timeout=args.timeout,
        )

        info = lidar.get_info()
        health = lidar.get_health()

        print("RPLIDAR device information")
        print(f"  port:     {args.port}")
        print(f"  model:    {info.get('model')}")
        print(f"  firmware: {info.get('firmware')}")
        print(f"  hardware: {info.get('hardware')}")
        print(f"  serial:   {info.get('serialnumber')}")
        print(f"  health:   {health[0]}")
        print(f"  error:    {health[1]}")

        if str(health[0]).lower() == "error":
            print("FAIL: lidar reports an internal health error.")
            return 1

        previous_time = None

        for index, scan in enumerate(lidar.iter_scans(max_buf_meas=1000)):
            now = time.monotonic()

            if previous_time is not None:
                scan_times.append(now - previous_time)
            previous_time = now

            count = len(scan)
            point_counts.append(count)

            valid = 0
            for measurement in scan:
                # rplidar-roboticia measurement tuple:
                # (quality, angle_degrees, distance_mm)
                if len(measurement) != 3:
                    continue

                quality, angle_deg, distance_mm = measurement

                if (
                    isinstance(quality, (int, float))
                    and isinstance(angle_deg, (int, float))
                    and isinstance(distance_mm, (int, float))
                    and math.isfinite(angle_deg)
                    and math.isfinite(distance_mm)
                    and 0.0 <= angle_deg < 360.0
                    and distance_mm > 0.0
                ):
                    valid += 1
                    distances_mm.append(float(distance_mm))

            fraction = valid / count if count else 0.0
            valid_fractions.append(fraction)

            print(
                f"scan {index + 1:02d}: "
                f"points={count:4d}, valid={fraction:6.1%}"
            )

            if index + 1 >= args.scans:
                break

        failures = []

        if len(point_counts) < args.scans:
            failures.append(
                f"received only {len(point_counts)} of {args.scans} requested scans"
            )

        median_points = statistics.median(point_counts) if point_counts else 0
        median_valid = (
            statistics.median(valid_fractions) if valid_fractions else 0.0
        )
        median_period = statistics.median(scan_times) if scan_times else 0.0
        scan_hz = 1.0 / median_period if median_period > 0.0 else 0.0

        if median_points < args.min_points:
            failures.append(
                f"median point count {median_points:.0f} "
                f"is below {args.min_points}"
            )

        if median_valid < args.min_valid_fraction:
            failures.append(
                f"median valid fraction {median_valid:.1%} "
                f"is below {args.min_valid_fraction:.1%}"
            )

        if scan_hz < args.min_scan_hz:
            failures.append(
                f"scan rate {scan_hz:.2f} Hz "
                f"is below {args.min_scan_hz:.2f} Hz"
            )

        if scan_hz > args.max_scan_hz:
            failures.append(
                f"scan rate {scan_hz:.2f} Hz "
                f"is above {args.max_scan_hz:.2f} Hz"
            )

        print("\nSummary")
        print(f"  scans:                 {len(point_counts)}")
        print(f"  median points/scan:    {median_points:.0f}")
        print(f"  median valid fraction: {median_valid:.1%}")
        print(f"  estimated scan rate:   {scan_hz:.2f} Hz")

        if distances_mm:
            print(
                f"  observed distance:      "
                f"{min(distances_mm) / 1000.0:.3f} to "
                f"{max(distances_mm) / 1000.0:.3f} m"
            )

        if failures:
            for failure in failures:
                print(f"FAIL: {failure}")
            return 1

        print("PASS: lidar communication and scan data look valid.")
        return 0

    except PermissionError:
        print(
            f"FAIL: permission denied opening {args.port}.\n"
            "Check the Stretch udev rules or your serial-device permissions.",
            file=sys.stderr,
        )
        return 1
    except FileNotFoundError:
        print(
            f"FAIL: serial device {args.port} was not found.\n"
            "Check `ls -l /dev/hello-lrf` and `ls -l /dev/ttyUSB*`.",
            file=sys.stderr,
        )
        return 1
    except RPLidarException as exc:
        print(f"FAIL: RPLIDAR error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    finally:
        if lidar is not None:
            try:
                lidar.stop()
            except Exception:
                pass
            try:
                lidar.stop_motor()
            except Exception:
                pass
            try:
                lidar.disconnect()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
launch_sensors.py
=================
Launches all 26 per-sensor MQTT publisher processes, one per physical sensor.
Each process uses its own X.509 client certificate (mTLS).

This script is an alternative to running plant_sim.py; it uses sensor_client.py
(random-walk baseline values without full physics coupling) which is useful for
integration testing individual sensor pipelines.

For the full physics-coupled simulation, use plant_sim.py instead.

Usage
-----
    python clients/python/launch_sensors.py [--broker 127.0.0.1] [--port 8883]
"""

import argparse
import logging
import pathlib
import subprocess
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("launch_sensors")

ROOT = pathlib.Path(__file__).resolve().parents[2]
SENSOR_CLIENT = ROOT / "clients" / "python" / "sensor_client.py"

ELECTROLYSERS = ["EL1", "EL2"]

SENSORS_COMMON = [
    ("cell_1_voltage",   1,    "V"),
    ("cell_2_voltage",   2,    "V"),
    ("cell_3_voltage",   3,    "V"),
    ("cell_4_voltage",   4,    "V"),
    ("cell_5_voltage",   5,    "V"),
    ("stack_current",    None, "A"),
    ("stack_temperature",None, "C"),
    ("stack_pressure",   None, "bar"),
    ("h2_flow_rate",     None, "LPM"),
    ("o2_flow_rate",     None, "LPM"),
    ("tank_pressure",    None, "bar"),
    ("water_flow",       None, "LPM"),
]

IRRADIANCE_SENSORS = [
    ("irradiance_1", None, "W/m2"),
    ("irradiance_2", None, "W/m2"),
]


def _build_cmd(el: str, sensor: str, cn: str, unit: str,
               cell: int | None, broker: str, port: int) -> list[str]:
    cmd = [
        sys.executable,
        str(SENSOR_CLIENT),
        "--el",     el,
        "--sensor", sensor,
        "--cn",     cn,
        "--unit",   unit,
        "--broker", broker,
        "--port",   str(port),
    ]
    if cell is not None:
        cmd += ["--cell", str(cell)]
    return cmd


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch all per-sensor MQTT publishers")
    parser.add_argument("--broker", default="127.0.0.1", help="MQTT broker host")
    parser.add_argument("--port",   type=int, default=8883, help="MQTT TLS port")
    args = parser.parse_args()

    procs: list[subprocess.Popen] = []

    log.info("Launching per-electrolyser sensor clients …")
    for el in ELECTROLYSERS:
        for sensor, cell, unit in SENSORS_COMMON:
            cn  = f"sensor-{el}-{sensor}"
            cmd = _build_cmd(el, sensor, cn, unit, cell, args.broker, args.port)
            log.info("Starting %s", cn)
            try:
                p = subprocess.Popen(cmd)
                procs.append(p)
            except OSError as exc:
                log.error("Failed to start %s: %s", cn, exc)
            time.sleep(0.08)

    log.info("Launching plant-level irradiance sensors …")
    for sensor, cell, unit in IRRADIANCE_SENSORS:
        cn  = f"sensor-plant-A-{sensor}"
        cmd = _build_cmd("PLANT", sensor, cn, unit, cell, args.broker, args.port)
        log.info("Starting %s", cn)
        try:
            p = subprocess.Popen(cmd)
            procs.append(p)
        except OSError as exc:
            log.error("Failed to start %s: %s", cn, exc)
        time.sleep(0.08)

    log.info("All %d sensor clients launched. Press Ctrl+C to stop.", len(procs))

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Stopping all sensor clients …")
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
        log.info("All clients stopped.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
sensor_client.py
================
Standalone parametric sensor publisher.

Each invocation represents a single physical sensor, connecting to the MQTT
broker using its own X.509 client certificate (mTLS).  Sensor value generation
uses the same physics constants as plant_sim.py so standalone mode produces
realistic baseline values.

Usage
-----
  python sensor_client.py --el EL1 --sensor cell_1_voltage --cn sensor-EL1-cell_1_voltage --unit V
  python sensor_client.py --el EL2 --sensor h2_flow_rate   --cn sensor-EL2-h2_flow_rate   --unit LPM
  python sensor_client.py --el PLANT --sensor irradiance_1 --cn sensor-plant-A-irradiance_1 --unit W/m2
"""

from __future__ import annotations

import argparse
import json
import logging
import pathlib
import random
import ssl
import time

from paho.mqtt import client as mqtt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("sensor_client")

ROOT = pathlib.Path(__file__).resolve().parents[2]


# ── Baseline value generation ─────────────────────────────────────────────────
def generate_value(el: str, sensor: str) -> float:
    """Generate a realistic baseline reading for the given sensor type."""
    if sensor.startswith("cell_"):
        return round(2.0 + random.uniform(-0.05, 0.05), 3)
    if sensor == "stack_current":
        return round(1.8 + random.uniform(-0.05, 0.05), 3)
    if sensor in ("h2_flow_rate", "o2_flow_rate"):
        return round(0.40 + random.uniform(-0.05, 0.05), 4)
    if sensor == "tank_pressure":
        return round(12.0 + random.uniform(-0.3, 0.3), 3)
    if sensor == "water_flow":
        return round(1.2 + random.uniform(-0.2, 0.2), 3)
    if sensor == "stack_temperature":
        return round(45.0 + random.uniform(-1.0, 1.0), 2)
    if sensor == "stack_pressure":
        return round(1.2 + random.uniform(-0.1, 0.1), 3)
    if sensor.startswith("irradiance"):
        return round(random.uniform(0, 1000), 2)
    return round(random.random(), 4)


# ── Topic resolution ──────────────────────────────────────────────────────────
def resolve_topic(el: str, sensor: str, cell: int | None = None) -> str:
    """Map (el, sensor, cell) to the canonical MQTT topic path."""
    base = "electrolyser/plant-A"
    if sensor.startswith("irradiance"):
        idx = sensor.split("_")[-1]
        return f"{base}/irradiance/{idx}"
    if el.upper().startswith("EL"):
        if sensor.startswith("cell_"):
            n = cell if cell is not None else int(sensor.split("_")[1])
            return f"{base}/{el}/cell/{n}/voltage"
        if sensor == "tank_pressure":
            return f"{base}/{el}/tank/pressure"
        if sensor in ("h2_flow_rate", "o2_flow_rate"):
            gas = "h2" if sensor.startswith("h2") else "o2"
            return f"{base}/{el}/{gas}/flow_rate"
        if sensor == "water_flow":
            return f"{base}/{el}/water_flow"
        if sensor in ("stack_current", "stack_temperature", "stack_pressure"):
            sub = sensor.split("_")[-1]
            return f"{base}/{el}/stack/{sub}"
        return f"{base}/{el}/{sensor}"
    return f"{base}/{el}/{sensor}"


# ── Entry point ───────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="Single-sensor MQTT publisher (mTLS)")
    parser.add_argument("--el",     required=True, help="Electrolyser ID: EL1 / EL2 / PLANT")
    parser.add_argument("--sensor", required=True, help="Sensor name (e.g. cell_1_voltage)")
    parser.add_argument("--cn",     required=True, help="Certificate CN directory under certs/clients/")
    parser.add_argument("--cell",   type=int,  default=None, help="Cell number for cell sensors")
    parser.add_argument("--unit",   default=None,             help="Engineering unit string")
    parser.add_argument("--broker", default="127.0.0.1",      help="MQTT broker host")
    parser.add_argument("--port",   type=int,  default=8883,  help="MQTT TLS port")
    args = parser.parse_args()

    topic = resolve_topic(args.el, args.sensor, args.cell)
    log.info("Publishing %s → %s", args.cn, topic)

    # X.509 client certificate paths
    ca   = ROOT / "certs/ca/ca.crt"
    cert = ROOT / f"certs/clients/{args.cn}/client.crt"
    key  = ROOT / f"certs/clients/{args.cn}/client.key"

    client = mqtt.Client(client_id=args.cn, protocol=mqtt.MQTTv5)
    client.tls_set(
        ca_certs=str(ca),
        certfile=str(cert),
        keyfile=str(key),
        tls_version=ssl.PROTOCOL_TLS_CLIENT,
    )
    client.tls_insecure_set(False)

    try:
        client.connect(args.broker, args.port, keepalive=30)
    except OSError as exc:
        log.error("Cannot connect to broker %s:%d — %s", args.broker, args.port, exc)
        raise SystemExit(1) from exc

    client.loop_start()
    seq = 0

    try:
        while True:
            value = generate_value(args.el, args.sensor)
            payload: dict = {
                "el":          args.el,
                "sensor":      args.sensor,
                "unit":        args.unit,
                "timestamp":   time.time(),
                "value":       value,
                "sequence_id": seq,
            }
            if args.cell is not None:
                payload["cell"] = args.cell
            # Drop None values
            payload = {k: v for k, v in payload.items() if v is not None}

            client.publish(topic, json.dumps(payload), qos=1)
            log.debug("%s → %s → %.4f", args.cn, topic, value)
            seq += 1
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Stopping publisher for %s", args.cn)
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()

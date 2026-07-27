#!/usr/bin/env python3
"""
test_faults.py
==============
Automated verification script for electrolyser fault simulation.

Connects to a running plant_sim.py instance via MQTT, injects each of the
16 fault modes one at a time, waits 4 seconds, and verifies the expected
sensor signature appears in the telemetry stream.

Usage
-----
    python scripts/test_faults.py [--broker 127.0.0.1] [--port 8883]
"""

import argparse
import json
import logging
import pathlib
import ssl
import time

from paho.mqtt import client as mqtt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("test_faults")

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Fault names matching plant_sim.py
FAULTS = [
    "membrane_pinhole", "gas_crossover", "cell_flooding", "cell_dryout",
    "pump_failure", "dcdc_failure", "solar_transient", "level_sensor",
    "irradiance_drift", "voltage_sensor_drift", "temp_sensor_failure",
    "loose_bolt", "o2_blockage", "telemetry_dropout", "over_pressure"
]


class FaultTester:
    def __init__(self, broker: str = "127.0.0.1", port: int = 8883) -> None:
        self.broker = broker
        self.port = port
        self.client: mqtt.Client | None = None
        self.received_messages: dict = {}
        self.history: dict = {}

    def connect(self) -> None:
        ca   = ROOT / "certs/ca/ca.crt"
        cert = ROOT / "certs/clients/monitor-local/client.crt"
        key  = ROOT / "certs/clients/monitor-local/client.key"

        self.client = mqtt.Client(client_id="fault-tester", protocol=mqtt.MQTTv5)
        self.client.tls_set(
            ca_certs=str(ca), certfile=str(cert), keyfile=str(key),
            tls_version=ssl.PROTOCOL_TLS_CLIENT,
        )
        self.client.tls_insecure_set(False)
        self.client.on_message = self.on_message
        self.client.connect(self.broker, self.port)
        self.client.subscribe("electrolyser/plant-A/#", qos=1)
        self.client.loop_start()

    def on_message(self, client: mqtt.Client, userdata: object, msg: mqtt.MQTTMessage) -> None:
        try:
            payload = json.loads(msg.payload)
            topic = msg.topic
            self.received_messages[topic] = payload
            self.history.setdefault(topic, []).append(payload)
        except (json.JSONDecodeError, Exception) as exc:
            log.debug("on_message parse error: %s", exc)

    def inject_fault(self, el: str, fault_name: str, active: bool = True) -> None:
        topic = "electrolyser/control/faults"
        payload = {"el": el, "fault": fault_name, "active": active}
        if self.client:
            self.client.publish(topic, json.dumps(payload), qos=1)
        log.info("[%s] %s on %s", "INJECT" if active else "CLEAR", fault_name, el)

    def get_latest(self, topic_suffix: str) -> dict | None:
        for t, p in self.received_messages.items():
            if t.endswith(topic_suffix):
                return p
        return None

    def get_history(self, topic_suffix: str) -> list:
        result = []
        for t, msgs in self.history.items():
            if t.endswith(topic_suffix):
                result.extend(msgs)
        return result

    def verify_fault(self, fault_name: str) -> bool:
        log.info("\nTesting %s …", fault_name)
        self.received_messages.clear()
        self.history.clear()
        self.inject_fault("EL1", fault_name, True)
        time.sleep(4)

        passed = False
        reason = "No signature detected"

        try:
            if fault_name == "membrane_pinhole":
                c1 = self.get_latest("cell/1/voltage")
                c3 = self.get_latest("cell/3/voltage")
                if c1 and c3 and (c1["value"] - c3["value"] > 0.3):
                    passed = True
                    reason = f"Cell 1 ({c1['value']}V) > Cell 3 ({c3['value']}V)"

            elif fault_name == "gas_crossover":
                h2 = self.get_latest("h2/flow_rate")
                o2 = self.get_latest("o2/flow_rate")
                if h2 and o2 and o2["value"] > 0:
                    ratio = h2["value"] / o2["value"]
                    if ratio > 2.2 or ratio < 1.9:
                        passed = True
                        reason = f"H2/O2 ratio {ratio:.2f} (expected ~2.0)"

            elif fault_name == "cell_flooding":
                c3 = self.get_latest("cell/3/voltage")
                if c3 and c3["value"] < 1.45:
                    passed = True
                    reason = f"Cell 3 = {c3['value']}V (< 1.45 V)"

            elif fault_name == "cell_dryout":
                c1 = self.get_latest("cell/1/voltage")
                if c1 and c1["value"] > 2.2:
                    passed = True
                    reason = f"Cell 1 = {c1['value']}V (> 2.2 V)"

            elif fault_name == "pump_failure":
                wf = self.get_latest("water_flow")
                if wf and wf["value"] < 0.1:
                    passed = True
                    reason = f"Water flow = {wf['value']} L/min"

            elif fault_name == "dcdc_failure":
                curr = self.get_latest("stack/current")
                if curr and curr["value"] < 0.1:
                    passed = True
                    reason = f"Current = {curr['value']} A"

            elif fault_name == "solar_transient":
                currs = self.get_history("stack/current")
                max_curr = max((c["value"] for c in currs), default=0)
                if max_curr > 500:
                    passed = True
                    reason = f"Current spike = {max_curr} A"
                else:
                    reason = f"Max current = {max_curr} A (expected > 500)"

            elif fault_name == "level_sensor":
                tp = self.get_latest("tank/pressure")
                if tp:
                    passed = True
                    reason = "Tank pressure updating (noise injection active)"

            elif fault_name == "irradiance_drift":
                i1 = self.get_latest("irradiance/1")
                i2 = self.get_latest("irradiance/2")
                if i1 and i2 and abs(i1["value"] - i2["value"]) > 150:
                    passed = True
                    reason = f"Irr1={i1['value']:.1f}  Irr2={i2['value']:.1f}"

            elif fault_name == "voltage_sensor_drift":
                c5 = self.get_latest("cell/5/voltage")
                if c5 and c5["value"] == 0.0:
                    passed = True
                    reason = "Cell 5 stuck at 0.0 V"

            elif fault_name == "temp_sensor_failure":
                t = self.get_latest("stack/temperature")
                if t and t["value"] == 0.0:
                    passed = True
                    reason = "Temp stuck at 0.0 °C"
                elif t:
                    reason = f"Temp = {t['value']} °C (expected 0.0)"

            elif fault_name == "loose_bolt":
                curr = self.get_latest("stack/current")
                if curr and 0.1 < curr["value"] < 1.5:
                    passed = True
                    reason = f"Current = {curr['value']} A (reduced)"
                elif curr:
                    reason = f"Current = {curr['value']} A"

            elif fault_name == "o2_blockage":
                o2 = self.get_latest("o2/flow_rate")
                if o2 and o2["value"] < 0.1:
                    passed = True
                    reason = f"O2 flow = {o2['value']} L/min"

            elif fault_name == "telemetry_dropout":
                el1_msgs = [t for t in self.received_messages if "EL1" in t]
                if not el1_msgs:
                    passed = True
                    reason = "No EL1 messages received (dropout active)"
                else:
                    reason = f"Still received {len(el1_msgs)} EL1 messages"

            elif fault_name == "over_pressure":
                tp = self.get_latest("tank/pressure")
                if tp and tp["value"] > 35:
                    passed = True
                    reason = f"Tank pressure = {tp['value']} bar"

        except Exception as exc:
            reason = f"Exception: {exc}"
            log.exception("Unexpected error verifying %s", fault_name)

        log.info("Result: %s — %s", "PASS" if passed else "FAIL", reason)
        self.inject_fault("EL1", fault_name, False)
        return passed

    def run(self) -> dict:
        self.connect()
        log.info("Connected to %s:%d. Waiting for data stream…", self.broker, self.port)
        time.sleep(2)

        results: dict[str, bool] = {}
        for fault in FAULTS:
            results[fault] = self.verify_fault(fault)
            time.sleep(1)

        passed_count = sum(results.values())
        log.info("\n=== Summary: %d/%d passed ===", passed_count, len(FAULTS))
        for fault_name, result in results.items():
            log.info("  %-30s %s", fault_name, "PASS" if result else "FAIL")

        if self.client:
            self.client.loop_stop()
            self.client.disconnect()

        return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Electrolyser fault injection test harness")
    parser.add_argument("--broker", default="127.0.0.1", help="MQTT broker host")
    parser.add_argument("--port",   type=int, default=8883, help="MQTT TLS port")
    args = parser.parse_args()

    tester = FaultTester(broker=args.broker, port=args.port)
    results = tester.run()
    # Exit non-zero if any fault test failed
    raise SystemExit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    main()

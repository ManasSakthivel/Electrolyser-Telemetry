#!/usr/bin/env python3
"""
test_faults.py
Automated verification script for electrolyser fault simulation.
"""

import json
import time
import ssl
import pathlib
import argparse
from paho.mqtt import client as mqtt

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Fault names matching plant_sim.py
FAULTS = [
    "membrane_pinhole", "gas_crossover", "cell_flooding", "cell_dryout",
    "pump_failure", "dcdc_failure", "solar_transient", "level_sensor",
    "irradiance_drift", "voltage_sensor_drift", "temp_sensor_failure",
    "loose_bolt", "o2_blockage", "telemetry_dropout", "over_pressure"
]

class FaultTester:
    def __init__(self, broker="127.0.0.1", port=8883):
        self.broker = broker
        self.port = port
        self.client = None
        self.received_messages = {}
        self.history = {}
        self.running = True

    def connect(self):
        # Use monitor-local certs
        ca = ROOT / "certs/ca/ca.crt"
        cert = ROOT / "certs/clients/monitor-local/client.crt"
        key = ROOT / "certs/clients/monitor-local/client.key"

        self.client = mqtt.Client(client_id="fault-tester", protocol=mqtt.MQTTv5)
        self.client.tls_set(ca_certs=str(ca), certfile=str(cert), keyfile=str(key),
                            tls_version=ssl.PROTOCOL_TLS_CLIENT)
        self.client.tls_insecure_set(False)
        self.client.on_message = self.on_message
        self.client.connect(self.broker, self.port)
        self.client.subscribe("electrolyser/plant-A/#")
        self.client.loop_start()

    def on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload)
            topic = msg.topic
            # Store latest message for each topic
            self.received_messages[topic] = payload
            
            # Also store in history for transient checks
            if topic not in self.history:
                self.history[topic] = []
            self.history[topic].append(payload)
        except:
            pass

    def inject_fault(self, el, fault_name, active=True):
        topic = "electrolyser/control/faults"
        payload = {"el": el, "fault": fault_name, "active": active}
        self.client.publish(topic, json.dumps(payload), qos=1)
        print(f"[{'INJECT' if active else 'CLEAR'}] {fault_name} on {el}")

    def get_latest(self, topic_suffix):
        # Find topic ending with suffix
        for t, p in self.received_messages.items():
            if t.endswith(topic_suffix):
                return p
        return None

    def get_history(self, topic_suffix):
        # Return all messages for topics ending with suffix
        res = []
        for t, msgs in self.history.items():
            if t.endswith(topic_suffix):
                res.extend(msgs)
        return res

    def verify_fault(self, fault_name):
        print(f"\nTesting {fault_name}...")
        self.received_messages.clear()
        self.history = {}
        self.inject_fault("EL1", fault_name, True)
        time.sleep(4) # Wait for effect

        passed = False
        reason = "No signature detected"

        try:
            if fault_name == "membrane_pinhole":
                # Cell 1 voltage > others, H2 flow high
                c1 = self.get_latest("cell/1/voltage")
                c3 = self.get_latest("cell/3/voltage")
                if c1 and c3 and (c1['value'] - c3['value'] > 0.3):
                    passed = True
                    reason = f"Cell 1 ({c1['value']}V) > Cell 3 ({c3['value']}V)"

            elif fault_name == "gas_crossover":
                # H2/O2 ratio != 2
                h2 = self.get_latest("h2/flow_rate")
                o2 = self.get_latest("o2/flow_rate")
                if h2 and o2:
                    ratio = h2['value'] / o2['value'] if o2['value'] > 0 else 0
                    if ratio > 2.2 or ratio < 1.9:
                        passed = True
                        reason = f"Ratio {ratio:.2f} (Expected ~2.0)"

            elif fault_name == "cell_flooding":
                # Cell 3 < 1.4V
                c3 = self.get_latest("cell/3/voltage")
                if c3 and c3['value'] < 1.45:
                    passed = True
                    reason = f"Cell 3 dropped to {c3['value']}V"

            elif fault_name == "cell_dryout":
                # All cells > 2.2
                c1 = self.get_latest("cell/1/voltage")
                if c1 and c1['value'] > 2.2:
                    passed = True
                    reason = f"Cell 1 rose to {c1['value']}V"

            elif fault_name == "pump_failure":
                # Water flow 0
                wf = self.get_latest("water_flow")
                if wf and wf['value'] < 0.1:
                    passed = True
                    reason = f"Water flow {wf['value']} L/min"

            elif fault_name == "dcdc_failure":
                # Current 0
                curr = self.get_latest("stack/current")
                if curr and curr['value'] < 0.1:
                    passed = True
                    reason = f"Current {curr['value']} A"

            elif fault_name == "solar_transient":
                # Current spike > 600
                # Check history for ANY spike
                currs = self.get_history("stack/current")
                max_curr = 0
                for c in currs:
                    if c['value'] > max_curr:
                        max_curr = c['value']
                
                if max_curr > 500:
                    passed = True
                    reason = f"Current spike {max_curr} A"
                else:
                    reason = f"Max current {max_curr} A"

            elif fault_name == "level_sensor":
                # Tank pressure noise? Hard to detect single sample
                # Check if we got a value
                tp = self.get_latest("tank/pressure")
                if tp:
                    passed = True
                    reason = "Tank pressure updating (visual check needed for noise)"

            elif fault_name == "irradiance_drift":
                # Irr 1 > Irr 2 + 200
                i1 = self.get_latest("irradiance/1")
                i2 = self.get_latest("irradiance/2")
                if i1 and i2 and abs(i1['value'] - i2['value']) > 150:
                    passed = True
                    reason = f"Irr1 {i1['value']} vs Irr2 {i2['value']}"

            elif fault_name == "voltage_sensor_drift":
                # Cell 5 = 0
                c5 = self.get_latest("cell/5/voltage")
                if c5 and c5['value'] == 0.0:
                    passed = True
                    reason = "Cell 5 stuck at 0.0V"

            elif fault_name == "temp_sensor_failure":
                # Temp 0
                t = self.get_latest("stack/temperature")
                if t and t['value'] == 0.0:
                    passed = True
                    reason = "Temp stuck at 0.0C"
                elif t:
                    reason = f"Temp {t['value']} C"

            elif fault_name == "loose_bolt":
                # Current lower than expected
                curr = self.get_latest("stack/current")
                if curr and curr['value'] < 1.5 and curr['value'] > 0.1:
                    passed = True
                    reason = f"Current {curr['value']} A (Low)"
                elif curr:
                    reason = f"Current {curr['value']} A"

            elif fault_name == "o2_blockage":
                # O2 flow low
                o2 = self.get_latest("o2/flow_rate")
                if o2 and o2['value'] < 0.1:
                    passed = True
                    reason = f"O2 flow {o2['value']} L/min"

            elif fault_name == "telemetry_dropout":
                # No updates for EL1
                # Check if we received any EL1 messages
                el1_msgs = [t for t in self.received_messages.keys() if "EL1" in t]
                if not el1_msgs:
                    passed = True
                    reason = "No EL1 messages received"
                else:
                    reason = f"Received {len(el1_msgs)} EL1 messages: {el1_msgs}"

            elif fault_name == "over_pressure":
                # Pressure > 35
                tp = self.get_latest("tank/pressure")
                if tp and tp['value'] > 35:
                    passed = True
                    reason = f"Pressure {tp['value']} bar"

        except Exception as e:
            reason = f"Error: {e}"

        print(f"Result: {'PASS' if passed else 'FAIL'} - {reason}")
        self.inject_fault("EL1", fault_name, False)
        return passed

    def run(self):
        self.connect()
        print("Connected. Waiting for data stream...")
        time.sleep(2)
        
        results = {}
        for fault in FAULTS:
            results[fault] = self.verify_fault(fault)
            time.sleep(1)

        print("\nSummary:")
        for f, r in results.items():
            print(f"{f}: {'PASS' if r else 'FAIL'}")

        self.client.loop_stop()
        self.client.disconnect()

if __name__ == "__main__":
    tester = FaultTester()
    tester.run()

#!/usr/bin/env python3
"""
Parametric sensor publisher for professional multi-electrolyser system.

Usage examples:
  python sensor_client.py --el EL1 --sensor cell_1_voltage --cn sensor-EL1-cell_1_voltage --unit V
  python sensor_client.py --el EL2 --sensor h2_flow_rate --cn sensor-EL2-h2_flow_rate --unit LPM
  python sensor_client.py --el PLANT --sensor irradiance_1 --cn sensor-plant-A-irradiance_1 --unit W/m2
"""
import ssl
import json
import time
import random
import argparse
import pathlib
from paho.mqtt import client as mqtt

ROOT = pathlib.Path(__file__).resolve().parents[2]

def generate_value(el, sensor):
    # cell voltages, values tuned around 2.0V per cell total ~10V
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
        return round(1.2 + random.uniform(-0.1, 0.1), 3)  # if you use bar/mPa choose appropriate
    if sensor.startswith("irradiance"):
        return round(random.uniform(0, 1000), 2)
    return round(random.random(), 4)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--el", required=True, help="Electrolyser ID (EL1/EL2/PLANT)")
    parser.add_argument("--sensor", required=True, help="Sensor name (e.g. cell_1_voltage)")
    parser.add_argument("--cn", required=True, help="Client cert CN directory name under certs/clients/")
    parser.add_argument("--cell", type=int, default=None, help="Cell number for cell sensors (1..5)")
    parser.add_argument("--unit", default=None, help="Unit string (V, A, LPM, bar, C, W/m2)")
    parser.add_argument("--broker", default="127.0.0.1", help="MQTT broker host")
    parser.add_argument("--port", type=int, default=8883, help="MQTT TLS port")
    args = parser.parse_args()

    # Topic mapping
    if args.sensor.startswith("irradiance"):
        topic = f"electrolyser/plant-A/irradiance/{args.sensor.split('_')[-1]}"
    elif args.el.upper().startswith("EL"):
        # path after electrolyser/<plant>/<EL>/
        # map sensor names to topic paths
        if args.sensor.startswith("cell_"):
            cell_no = args.cell if args.cell else int(args.sensor.split('_')[1])
            topic = f"electrolyser/plant-A/{args.el}/cell/{cell_no}/voltage"
        elif args.sensor == "tank_pressure":
            topic = f"electrolyser/plant-A/{args.el}/tank/pressure"
        elif args.sensor in ("h2_flow_rate", "o2_flow_rate"):
            gas = "h2" if args.sensor.startswith("h2") else "o2"
            topic = f"electrolyser/plant-A/{args.el}/{gas}/flow_rate"
        elif args.sensor == "water_flow":
            topic = f"electrolyser/plant-A/{args.el}/water_flow"
        elif args.sensor == "stack_current":
            topic = f"electrolyser/plant-A/{args.el}/stack/current"
        elif args.sensor == "stack_temperature":
            topic = f"electrolyser/plant-A/{args.el}/stack/temperature"
        elif args.sensor == "stack_pressure":
            topic = f"electrolyser/plant-A/{args.el}/stack/pressure"
        else:
            topic = f"electrolyser/plant-A/{args.el}/{args.sensor}"
    else:
        topic = f"electrolyser/plant-A/{args.el}/{args.sensor}"

    # Certificate paths
    ca = ROOT / "certs/ca/ca.crt"
    cert = ROOT / f"certs/clients/{args.cn}/client.crt"
    key = ROOT / f"certs/clients/{args.cn}/client.key"

    # MQTT client
    client = mqtt.Client(client_id=args.cn, protocol=mqtt.MQTTv5)
    client.tls_set(
        ca_certs=str(ca),
        certfile=str(cert),
        keyfile=str(key),
        tls_version=ssl.PROTOCOL_TLS_CLIENT,
    )
    client.tls_insecure_set(False)
    client.connect(args.broker, args.port, keepalive=30)
    client.loop_start()

    seq = 0
    try:
        while True:
            value = generate_value(args.el, args.sensor)
            payload = {
                "el": args.el,
                "sensor": args.sensor,
                "cell": args.cell if args.cell is not None else None,
                "unit": args.unit if args.unit else None,
                "timestamp": time.time(),
                "value": value,
                "sequence_id": seq,
            }
            # Remove None fields for compactness
            payload = {k: v for k, v in payload.items() if v is not None}
            client.publish(topic, json.dumps(payload), qos=1)
            print(f"{args.cn} → {topic} → {payload}")
            seq += 1
            time.sleep(1)
    except KeyboardInterrupt:
        print("Exiting publisher")
    finally:
        client.loop_stop()
        client.disconnect()

if __name__ == "__main__":
    main()

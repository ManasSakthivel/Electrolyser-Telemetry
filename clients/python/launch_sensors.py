#!/usr/bin/env python3
import subprocess
import time
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]

electrolysers = ["EL1", "EL2"]

sensors_common = [
  ("cell_1_voltage", 1, "V"),
  ("cell_2_voltage", 2, "V"),
  ("cell_3_voltage", 3, "V"),
  ("cell_4_voltage", 4, "V"),
  ("cell_5_voltage", 5, "V"),
  ("stack_current", None, "A"),
  ("stack_temperature", None, "C"),
  ("stack_pressure", None, "bar"),
  ("h2_flow_rate", None, "LPM"),
  ("o2_flow_rate", None, "LPM"),
  ("tank_pressure", None, "bar"),
  ("water_flow", None, "LPM"),
]

# two irradiance sensors at plant level
irradiance = [("irradiance_1", None, "W/m2"), ("irradiance_2", None, "W/m2")]

procs = []

print("Launching professional multi-electrolyser sensor clients...\n")

# per-electrolyser devices
for el in electrolysers:
    for sensor, cell, unit in sensors_common:
        cn = f"sensor-{el}-{sensor}"
        cmd = [
            "python3",
            str(ROOT / "clients" / "python" / "sensor_client.py"),
            "--el", el,
            "--sensor", sensor,
            "--cn", cn,
            "--unit", unit,
        ]
        if cell:
            cmd += ["--cell", str(cell)]
        print("Starting:", " ".join(cmd))
        p = subprocess.Popen(cmd)
        procs.append(p)
        time.sleep(0.08)

# plant-level irradiance
for sensor, cell, unit in irradiance:
    cn = f"sensor-plant-A-{sensor}"
    cmd = [
        "python3",
        str(ROOT / "clients" / "python" / "sensor_client.py"),
        "--el", "PLANT",
        "--sensor", sensor,
        "--cn", cn,
        "--unit", unit,
    ]
    print("Starting:", " ".join(cmd))
    p = subprocess.Popen(cmd)
    procs.append(p)
    time.sleep(0.08)

print("\nAll sensors launched. Press Ctrl+C to stop.\n")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("Stopping sensors...")
    for p in procs:
        p.terminate()

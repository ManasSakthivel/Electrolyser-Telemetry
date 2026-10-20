#!/usr/bin/env python3
"""
export_dataset.py
=================
Labelled telemetry dataset exporter.

Two operation modes
-------------------
1. **Live mode** (default) — subscribes to the MQTT broker, collects sensor
   readings into time-windowed rows, labels each row with the active fault(s)
   from the /status topic, then flushes to Parquet + CSV.

2. **Synthetic mode** (``--synthetic``) — generates a representative simulated
   dataset without a live broker.  Uses the same Butler-Volmer physics as
   ``plant_sim.py`` and injects all 16 fault classes in rotation.  Intended for
   notebook development, CI, and demo purposes.

Output schema (one row per telemetry tick)
------------------------------------------
  timestamp, el, cell_1..5_voltage, stack_current, stack_temperature,
  stack_pressure, h2_flow_rate, o2_flow_rate, tank_pressure, water_flow,
  irradiance_1, irradiance_2, fault_label (str), is_fault (bool)

Usage
-----
  # Live collection (requires running simulator):
  python scripts/export_dataset.py --duration 600 --out data/telemetry_labelled.parquet

  # Synthetic dataset (no broker needed):
  python scripts/export_dataset.py --synthetic --rows 1200 --out data/telemetry_labelled.parquet

Requirements
------------
  pip install paho-mqtt pyarrow pandas
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import math
import pathlib
import random
import ssl
import time

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from paho.mqtt import client as mqtt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("export_dataset")

ROOT = pathlib.Path(__file__).resolve().parents[1]

# ── Schema ────────────────────────────────────────────────────────────────────
FEATURES = [
    "cell_1_voltage", "cell_2_voltage", "cell_3_voltage",
    "cell_4_voltage", "cell_5_voltage",
    "stack_current", "stack_temperature", "stack_pressure",
    "h2_flow_rate", "o2_flow_rate", "tank_pressure", "water_flow",
    "irradiance_1", "irradiance_2",
]

_SENSOR_TO_FEATURE = {f: f for f in FEATURES}

# Fault classes for synthetic generation (mirrors FAULT_NAMES in plant_sim.py)
_FAULT_CLASSES = [
    "normal", "membrane_pinhole", "gas_crossover", "cell_flooding",
    "cell_dryout", "pump_failure", "dcdc_failure", "solar_transient",
    "level_sensor", "irradiance_drift", "voltage_sensor_drift",
    "temp_sensor_failure", "loose_bolt", "o2_blockage",
    "telemetry_dropout", "over_pressure",
]


# ── Synthetic dataset generator ───────────────────────────────────────────────

def _three_term_voltage(
    i: float,
    u_rev: float   = 1.23,
    r_ohm: float   = 0.4,
    alpha: float   = 0.5,
    i0: float      = 1e-3,
    i_lim: float   = 6.0,
) -> float:
    """Three-term per-cell voltage: Butler-Volmer activation + Nernst concentration + Ohmic.

    V = U_rev + (RT/αF)·arcsinh(I/2I₀) + (RT/2F)·ln(I_lim/(I_lim−I)) + R_ohm·I
    """
    if i <= 0.0:
        return u_rev
    rt_af = 8.314 * 298.15 / (alpha * 96485.0)
    rt_2f = 8.314 * 298.15 / (2.0 * 96485.0)
    v_act  = rt_af * math.asinh(i / (2.0 * i0))
    margin = max(i_lim - i, 1e-6)
    v_conc = rt_2f * math.log(i_lim / margin)
    return u_rev + v_act + v_conc + r_ohm * i


def _generate_row(t: float, el: str, fault: str, irr: float,
                  i_stack: float, tank_bar: float,
                  r_ohm: float = 0.4, eta_f: float = 0.95,
                  mem_resistance_drift: float = 0.0) -> dict:
    """Generate one synthetic telemetry row for the given state.

    Parameters
    ----------
    r_ohm : float
        Per-cell Ohmic resistance — varies ±15% across cells (manufacturing spread).
    eta_f : float
        Faraday efficiency — varies 0.90–0.98 across stacks.
    mem_resistance_drift : float
        Additive membrane resistance drift (Ω) — simulates slow degradation over time.
    """
    effective_r_ohm = r_ohm + mem_resistance_drift
    noise = lambda s=0.02: random.uniform(-s, s)

    cells = [
        round(_three_term_voltage(i_stack, r_ohm=effective_r_ohm * random.uniform(0.97, 1.03)) + noise(), 4)
        for _ in range(5)
    ]
    h2    = round(max(0.0, i_stack * 0.22 * eta_f / 0.95 + noise(0.01)), 4)
    o2    = round(h2 / 2.0 * 0.99, 4)
    temp  = round(45.0 + 0.5 * i_stack + noise(0.5), 2)
    pres  = round(1.2 + noise(0.05), 3)
    water = round(max(0.0, 1.2 * (i_stack / 1.8)), 3)
    tank  = round(tank_bar + noise(0.01), 4)

    # ── Apply fault signatures ─────────────────────────────────────────────
    if fault == "membrane_pinhole":
        cells[0] += 0.5; cells[1] += 0.4; h2 *= 1.2
    elif fault == "gas_crossover":
        o2 = round(h2 / 2.3, 4)
    elif fault == "cell_flooding":
        cells[2] = 1.35; cells[3] = 1.38
    elif fault == "cell_dryout":
        cells = [max(c, 2.25) for c in cells]; temp += 5.0
    elif fault == "pump_failure":
        water = 0.0
    elif fault == "dcdc_failure":
        i_stack = 0.0; cells = [1.23] * 5; h2 = 0.0; o2 = 0.0
    elif fault == "solar_transient":
        i_stack = 650.0
    elif fault == "level_sensor":
        tank += random.uniform(-2.0, 2.0)
    elif fault == "irradiance_drift":
        irr += 300.0
    elif fault == "voltage_sensor_drift":
        cells[4] = 0.0
    elif fault == "temp_sensor_failure":
        temp = 0.0
    elif fault == "loose_bolt":
        i_stack *= 0.75; cells = [round(_three_term_voltage(i_stack, r_ohm=effective_r_ohm) + noise(), 4)] * 5
    elif fault == "o2_blockage":
        o2 = round(o2 * 0.2, 4)
    elif fault == "telemetry_dropout":
        # Row produced but all sensor values are NaN (simulates missing messages)
        cells = [float("nan")] * 5
        i_stack = float("nan"); temp = float("nan")
        h2 = float("nan"); o2 = float("nan")
    elif fault == "over_pressure":
        tank = 40.0

    return {
        "timestamp":        round(t, 3),
        "el":               el,
        "cell_1_voltage":   cells[0],
        "cell_2_voltage":   cells[1],
        "cell_3_voltage":   cells[2],
        "cell_4_voltage":   cells[3],
        "cell_5_voltage":   cells[4],
        "stack_current":    round(i_stack, 4),
        "stack_temperature": temp,
        "stack_pressure":   pres,
        "h2_flow_rate":     h2,
        "o2_flow_rate":     o2,
        "tank_pressure":    tank,
        "water_flow":       water,
        "irradiance_1":     round(irr, 2),
        "irradiance_2":     round(irr * 0.95 + noise(10), 2),
        "fault_label":      fault,
        "is_fault":         fault != "normal",
    }


def generate_synthetic_dataset(
    rows_per_class: int = 500,
    seed: int = 42,
    el: str = "EL1",
) -> pd.DataFrame:
    """
    Generate a fully labelled synthetic telemetry dataset without a live broker.

    Parameters
    ----------
    rows_per_class : int
        Number of rows to generate for each of the 16 fault classes.
        Default raised to 500 to provide statistically stable ML evaluation.
        Total rows ≈ rows_per_class × 16 classes × 2 electrolysers.
    seed : int
        Random seed for reproducibility.
    el : str
        Electrolyser ID ('EL1', 'EL2', or 'both').

    Returns
    -------
    pd.DataFrame
        Labelled dataset with the canonical feature columns.

    Notes
    -----
    Realistic variability is injected at three levels to prevent the classifier
    from exploiting simulation artefacts:
      1. Per-stack R_ohm drawn from N(0.4, 0.06²) — ±15% manufacturing spread.
      2. Per-stack Faraday efficiency η_F drawn from U(0.90, 0.98).
      3. Per-tick additive membrane resistance drift of +0.001 Ω/row — simulates
         slow degradation over the collection window.
    """
    random.seed(seed)
    electrolysers = ["EL1", "EL2"] if el == "both" else [el]
    all_rows: list[dict] = []

    for el_id in electrolysers:
        t = time.time()
        tank_bar = 1.0
        # Per-stack variability: manufacturing spread in Ohmic resistance & Faraday efficiency
        stack_r_ohm = max(0.25, random.gauss(0.4, 0.06))       # ±15% spread
        stack_eta_f = random.uniform(0.90, 0.98)                # realistic efficiency range

        for fault_class in _FAULT_CLASSES:
            mem_drift = 0.0                                      # reset drift for each fault class
            # Ramp up irradiance sinusoidally — more realistic than constant current
            for k in range(rows_per_class):
                irr = 500.0 + 400.0 * math.sin(2 * math.pi * k / rows_per_class)
                i_stack = 1.8 * (irr / 1000.0)
                tank_bar = min(tank_bar + i_stack * 0.001, 29.0)
                # Slow membrane resistance drift: +0.001 Ω per row across the window
                mem_drift += 0.001 / rows_per_class
                row = _generate_row(
                    t + k, el_id, fault_class, irr, i_stack, tank_bar,
                    r_ohm=stack_r_ohm, eta_f=stack_eta_f,
                    mem_resistance_drift=mem_drift,
                )
                all_rows.append(row)
            t += rows_per_class

    df = pd.DataFrame(all_rows)
    df = df.sort_values(["el", "timestamp"]).reset_index(drop=True)
    log.info("Synthetic dataset: %d rows  ×  %d features  ×  %d fault classes",
             len(df), len(FEATURES), len(_FAULT_CLASSES))
    log.info("Label distribution:\n%s", df["fault_label"].value_counts().to_string())
    return df


# ── Live MQTT collector ───────────────────────────────────────────────────────

class TelemetryCollector:
    """
    Assembles per-tick rows from individual MQTT sensor messages.

    For each electrolyser (EL1/EL2) we maintain a running accumulator dict.
    When ALL features have been seen at least once, the row is emitted and
    the accumulator is reset.  The fault label is taken from the most recent
    /status message.
    """

    def __init__(self, duration_s: float) -> None:
        self.duration = duration_s
        self.start_time = time.time()
        self.rows: list[dict] = []

        self._buf: dict[str, dict[str, float | None]] = {
            el: {f: None for f in FEATURES} for el in ("EL1", "EL2")
        }
        self._fault_labels: dict[str, str] = {"EL1": "normal", "EL2": "normal"}
        self._ts: dict[str, float] = {"EL1": 0.0, "EL2": 0.0}

    def handle_message(self, topic: str, raw: bytes | str) -> None:
        try:
            if isinstance(raw, bytes):
                msg = json.loads(raw.decode("utf-8"))
            else:
                msg = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return

        el = msg.get("stack_id") or msg.get("el")
        sensor = msg.get("sensor_id") or msg.get("sensor", "")

        metrics = msg.get("metrics")
        if isinstance(metrics, dict) and "value" in metrics:
            value = metrics["value"]
        else:
            value = msg.get("value")

        ts_raw = msg.get("ts") or msg.get("timestamp")
        if isinstance(ts_raw, str):
            try:
                dt = datetime.datetime.fromisoformat(ts_raw)
                ts = dt.timestamp()
            except ValueError:
                ts = time.time()
        elif isinstance(ts_raw, (int, float)):
            ts = float(ts_raw)
        else:
            ts = time.time()

        if topic.endswith("/status") and el in ("EL1", "EL2"):
            faults = msg.get("active_faults") or []
            self._fault_labels[el] = ",".join(faults) if faults else "normal"
            return

        if el == "PLANT":
            feature = _SENSOR_TO_FEATURE.get(sensor)
            if feature and value is not None:
                for el_buf in self._buf.values():
                    el_buf[feature] = float(value)
            return

        if el not in self._buf:
            return
        feature = _SENSOR_TO_FEATURE.get(sensor)
        if feature and value is not None:
            self._buf[el][feature] = float(value)
            self._ts[el] = ts

        if all(v is not None for v in self._buf[el].values()):
            row = {
                "timestamp": self._ts[el],
                "el":        el,
                **self._buf[el],
                "fault_label": self._fault_labels[el],
                "is_fault":    self._fault_labels[el] != "normal",
            }
            self.rows.append(row)
            self._buf[el] = {f: None for f in FEATURES}

    def is_done(self) -> bool:
        return (time.time() - self.start_time) >= self.duration


# ── Shared export logic ───────────────────────────────────────────────────────

def _write_outputs(df: pd.DataFrame, out_path: pathlib.Path) -> None:
    """Write Parquet (primary) and CSV (secondary) to disk."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(df), str(out_path))
    log.info("Wrote %d rows → %s", len(df), out_path)

    csv_path = out_path.with_suffix(".csv")
    df.to_csv(str(csv_path), index=False)
    log.info("Wrote CSV  → %s", csv_path)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Export labelled telemetry dataset")
    parser.add_argument("--broker",    default="127.0.0.1")
    parser.add_argument("--port",      type=int, default=8883)
    parser.add_argument("--duration",  type=float, default=600.0,
                        help="Live collection duration in seconds (default 600)")
    parser.add_argument("--out",       default="data/telemetry_labelled.parquet",
                        help="Output Parquet file path")
    parser.add_argument("--cn",        default="monitor-local",
                        help="Certificate CN for MQTT connection (live mode)")
    parser.add_argument("--synthetic", action="store_true",
                        help="Generate synthetic dataset without a live broker")
    parser.add_argument("--rows",      type=int, default=80,
                        help="Rows per fault class in synthetic mode (default 80)")
    parser.add_argument("--seed",      type=int, default=42,
                        help="Random seed for synthetic generation")
    args = parser.parse_args()

    out_path = pathlib.Path(args.out)

    # ── Synthetic mode ─────────────────────────────────────────────────────
    if args.synthetic:
        log.info("Synthetic mode: %d rows/class, seed=%d", args.rows, args.seed)
        df = generate_synthetic_dataset(rows_per_class=args.rows, seed=args.seed, el="both")
        _write_outputs(df, out_path)
        return

    # ── Live mode ──────────────────────────────────────────────────────────
    collector = TelemetryCollector(args.duration)

    ca   = ROOT / "certs/ca/ca.crt"
    cert = ROOT / f"certs/clients/{args.cn}/client.crt"
    key  = ROOT / f"certs/clients/{args.cn}/client.key"

    client = mqtt.Client(client_id="dataset-exporter", protocol=mqtt.MQTTv5)
    client.tls_set(
        ca_certs=str(ca), certfile=str(cert), keyfile=str(key),
        tls_version=ssl.PROTOCOL_TLS_CLIENT,
    )
    client.tls_insecure_set(False)

    def on_message(c: mqtt.Client, userdata: object, msg: mqtt.MQTTMessage) -> None:
        collector.handle_message(msg.topic, msg.payload)

    client.on_message = on_message

    try:
        client.connect(args.broker, args.port, keepalive=30)
    except OSError as exc:
        log.error("Cannot connect to broker: %s", exc)
        raise SystemExit(1) from exc

    client.subscribe("electrolyser/plant-A/#", qos=1)
    client.loop_start()

    log.info("Collecting for %.0f s — broker %s:%d …", args.duration, args.broker, args.port)
    while not collector.is_done():
        time.sleep(1.0)

    client.loop_stop()
    client.disconnect()

    if not collector.rows:
        log.error("No rows collected — is the simulator running?")
        log.error("Tip: run 'make sim' in a separate terminal, or use --synthetic for offline mode.")
        raise SystemExit(1)

    df = pd.DataFrame(collector.rows)
    df = df.sort_values("timestamp").reset_index(drop=True)
    _write_outputs(df, out_path)

    fault_counts = df["fault_label"].value_counts()
    log.info("Label distribution:\n%s", fault_counts.to_string())


if __name__ == "__main__":
    main()

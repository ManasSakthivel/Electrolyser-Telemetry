#!/usr/bin/env python3
"""
leadtime_experiment.py
======================
Measures the early-detection lead time of the LSTM Autoencoder relative to
a threshold-based alarm system on per-fault-class injection traces.

Methodology
-----------
For each of the 15 fault classes (excluding "normal"):
  1.  Generate a 10-minute (600-row) trace: 300 normal rows followed immediately
      by 300 rows with the fault active.
  2.  Compute per-tick reconstruction errors using the trained LSTM Autoencoder.
  3.  Record t_LSTM  = first tick where recon_error > threshold (μ + 3σ on normal).
  4.  Record t_alarm = first tick where any individual sensor value crosses its
      hard-coded safety threshold (simulating a traditional threshold alarm).
  5.  Lead time = t_alarm − t_LSTM  (positive = LSTM detected earlier).

Results are written to:
    data/leadtime_experiment.json   (machine-readable)
    data/leadtime_comparison.png    (bar chart)

Usage
-----
    python scripts/leadtime_experiment.py \\
        --rows 600 --window 30 --model data/lstm_autoencoder.pt \\
        --out data/leadtime_experiment.json

    # Quick synthetic run (no pre-trained model required — trains on the fly):
    python scripts/leadtime_experiment.py --train-inline --rows 600

Requirements
------------
    pip install torch pandas numpy matplotlib scikit-learn
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import random
import sys
from typing import Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
from torch import nn
from sklearn.preprocessing import StandardScaler
from torch.utils.data import DataLoader, TensorDataset

# Locate project root and reuse the export_dataset helpers
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

# ── Inline physics (mirror of export_dataset._three_term_voltage) ────────────
_RT_AF = 8.314 * 298.15 / (0.5 * 96485.0)
_RT_2F = 8.314 * 298.15 / (2.0 * 96485.0)


def _cell_voltage(i: float, r_ohm: float = 0.4, i0: float = 1e-3,
                  i_lim: float = 6.0) -> float:
    if i <= 0.0:
        return 1.23
    v_act  = _RT_AF * math.asinh(i / (2.0 * i0))
    v_conc = _RT_2F * math.log(i_lim / max(i_lim - i, 1e-6))
    return 1.23 + v_act + v_conc + r_ohm * i


FEATURES = [
    "cell_1_voltage", "cell_2_voltage", "cell_3_voltage",
    "cell_4_voltage", "cell_5_voltage",
    "stack_current", "stack_temperature", "stack_pressure",
    "h2_flow_rate", "o2_flow_rate", "tank_pressure", "water_flow",
    "irradiance_1", "irradiance_2",
]

# Hard-coded threshold-based alarm rules (mirrors safety checks in plant_sim.py)
ALARM_RULES: Dict[str, callable] = {
    "cell_dryout":          lambda r: any(r.get(f"cell_{i}_voltage", 0) > 2.2 for i in range(1, 6)),
    "pump_failure":         lambda r: r.get("water_flow", 1) < 0.05,
    "over_pressure":        lambda r: r.get("tank_pressure", 0) > 30.0,
    "dcdc_failure":         lambda r: r.get("stack_current", 1) < 0.05,
    "membrane_pinhole":     lambda r: r.get("cell_1_voltage", 0) > 2.5,
    "gas_crossover":        lambda r: abs(r.get("h2_flow_rate", 2) / max(r.get("o2_flow_rate", 1), 1e-6) - 2.0) > 0.4,
    "cell_flooding":        lambda r: any(r.get(f"cell_{i}_voltage", 2) < 1.4 for i in (3, 4)),
    "loose_bolt":           lambda r: r.get("stack_current", 2) < 0.8,
    "solar_transient":      lambda r: r.get("stack_current", 0) > 100.0,
    "level_sensor":         lambda r: abs(r.get("tank_pressure", 0) - 5.0) > 3.0,
    "irradiance_drift":     lambda r: r.get("irradiance_1", 0) - r.get("irradiance_2", 0) > 250.0,
    "voltage_sensor_drift": lambda r: r.get("cell_5_voltage", 1) < 0.1,
    "temp_sensor_failure":  lambda r: r.get("stack_temperature", 45) < 1.0,
    "o2_blockage":          lambda r: r.get("o2_flow_rate", 1) < 0.05,
    "telemetry_dropout":    lambda r: all(math.isnan(r.get(f, float("nan"))) for f in ["stack_current", "h2_flow_rate"]),
}

FAULT_CLASSES = [
    "membrane_pinhole", "gas_crossover", "cell_flooding", "cell_dryout",
    "pump_failure", "dcdc_failure", "solar_transient", "level_sensor",
    "irradiance_drift", "voltage_sensor_drift", "temp_sensor_failure",
    "loose_bolt", "o2_blockage", "telemetry_dropout", "over_pressure",
]


# ── Inline row generator ──────────────────────────────────────────────────────

def _make_row(k: int, fault: Optional[str] = None,
              r_ohm: float = 0.4, eta_f: float = 0.95) -> dict:
    irr     = 500.0 + 400.0 * math.sin(2 * math.pi * k / 600.0)
    i_stack = 1.8 * (irr / 1000.0)
    n       = lambda s=0.02: random.uniform(-s, s)  # noqa: E731
    cells   = [round(_cell_voltage(i_stack, r_ohm=r_ohm * random.uniform(0.97, 1.03)) + n(), 4)
               for _ in range(5)]
    h2      = round(max(0.0, i_stack * 0.22 * eta_f / 0.95 + n(0.01)), 4)
    o2      = round(h2 / 2.0 * 0.99, 4)
    temp    = round(45.0 + 0.5 * i_stack + n(0.5), 2)
    pres    = round(1.2 + n(0.05), 3)
    water   = round(max(0.0, 1.2 * (i_stack / 1.8)), 3)
    tank    = round(1.0 + i_stack * 0.001 * k, 4)
    irr2    = round(irr * 0.95 + n(10), 2)

    row = {
        "cell_1_voltage": cells[0], "cell_2_voltage": cells[1],
        "cell_3_voltage": cells[2], "cell_4_voltage": cells[3],
        "cell_5_voltage": cells[4], "stack_current": round(i_stack, 4),
        "stack_temperature": temp, "stack_pressure": pres,
        "h2_flow_rate": h2, "o2_flow_rate": o2,
        "tank_pressure": tank, "water_flow": water,
        "irradiance_1": round(irr, 2), "irradiance_2": irr2,
    }

    if fault == "membrane_pinhole":
        row["cell_1_voltage"] += 0.5; row["cell_2_voltage"] += 0.4; row["h2_flow_rate"] *= 1.2
    elif fault == "gas_crossover":
        row["o2_flow_rate"] = round(h2 / 2.3, 4)
    elif fault == "cell_flooding":
        row["cell_3_voltage"] = 1.35; row["cell_4_voltage"] = 1.38
    elif fault == "cell_dryout":
        row = {**row, **{f"cell_{i}_voltage": max(cells[i-1], 2.25) for i in range(1, 6)}}
        row["stack_temperature"] = temp + 5.0
    elif fault == "pump_failure":
        row["water_flow"] = 0.0
    elif fault == "dcdc_failure":
        row["stack_current"] = 0.0
        for i in range(1, 6): row[f"cell_{i}_voltage"] = 1.23
        row["h2_flow_rate"] = 0.0; row["o2_flow_rate"] = 0.0
    elif fault == "solar_transient":
        row["stack_current"] = 650.0
    elif fault == "level_sensor":
        row["tank_pressure"] += random.uniform(-2.0, 2.0)
    elif fault == "irradiance_drift":
        row["irradiance_1"] += 300.0
    elif fault == "voltage_sensor_drift":
        row["cell_5_voltage"] = 0.0
    elif fault == "temp_sensor_failure":
        row["stack_temperature"] = 0.0
    elif fault == "loose_bolt":
        row["stack_current"] *= 0.75
    elif fault == "o2_blockage":
        row["o2_flow_rate"] = round(o2 * 0.2, 4)
    elif fault == "telemetry_dropout":
        for f in ["stack_current", "h2_flow_rate", "o2_flow_rate",
                  "stack_temperature"]:
            row[f] = float("nan")
    elif fault == "over_pressure":
        row["tank_pressure"] = 40.0

    return row


def _generate_trace(fault: str, n_normal: int = 300, n_fault: int = 300,
                    seed: int = 42) -> Tuple[List[dict], List[int]]:
    """Generate a (n_normal + n_fault) row trace with a hard fault onset."""
    random.seed(seed)
    r_ohm = max(0.25, random.gauss(0.4, 0.06))
    eta_f = random.uniform(0.90, 0.98)
    rows   = [_make_row(k, fault=None, r_ohm=r_ohm, eta_f=eta_f) for k in range(n_normal)]
    rows  += [_make_row(n_normal + k, fault=fault, r_ohm=r_ohm, eta_f=eta_f) for k in range(n_fault)]
    labels = [0] * n_normal + [1] * n_fault
    return rows, labels


# ── LSTM Autoencoder ──────────────────────────────────────────────────────────

class LSTMAutoencoder(nn.Module):
    def __init__(self, n_features: int, hidden: int = 64, n_layers: int = 2,
                 dropout: float = 0.2) -> None:
        super().__init__()
        self.encoder = nn.LSTM(n_features, hidden, n_layers, batch_first=True, dropout=dropout)
        self.decoder = nn.LSTM(hidden, hidden, n_layers, batch_first=True, dropout=dropout)
        self.fc_out  = nn.Linear(hidden, n_features)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        _, (h, c) = self.encoder(x)
        latent = h[-1].unsqueeze(1).repeat(1, x.size(1), 1)
        out, _ = self.decoder(latent, (h, c))
        return self.fc_out(out)


def _train_lstm(X_normal: np.ndarray, window: int = 30,
                epochs: int = 30, batch: int = 64) -> Tuple[LSTMAutoencoder, float]:
    """Train LSTM Autoencoder on normal windows; return model and threshold."""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    seqs = []
    for i in range(len(X_normal) - window + 1):
        seqs.append(X_normal[i:i + window])
    seqs = np.array(seqs, dtype=np.float32)
    split = int(0.8 * len(seqs))
    train_t = torch.tensor(seqs[:split])
    val_t   = torch.tensor(seqs[split:])
    train_dl = DataLoader(TensorDataset(train_t), batch_size=batch, shuffle=True)
    val_dl   = DataLoader(TensorDataset(val_t),   batch_size=batch)

    model = LSTMAutoencoder(X_normal.shape[1]).to(device)
    opt   = torch.optim.Adam(model.parameters(), lr=1e-3)
    crit  = nn.MSELoss()
    for ep in range(epochs):
        model.train()
        for (xb,) in train_dl:
            xb   = xb.to(device)
            loss = crit(model(xb), xb)
            opt.zero_grad(); loss.backward(); opt.step()

    # Calibrate threshold on normal validation windows
    model.eval()
    val_errs = []
    with torch.no_grad():
        for (xb,) in val_dl:
            xb  = xb.to(device)
            err = ((model(xb) - xb) ** 2).mean(dim=(1, 2)).cpu().numpy()
            val_errs.extend(err)
    val_errs = np.array(val_errs)
    threshold = float(val_errs.mean() + 3.0 * val_errs.std())
    return model, threshold


def _detection_tick(model: LSTMAutoencoder, scaler: StandardScaler,
                    rows: List[dict], threshold: float,
                    window: int = 30) -> Optional[int]:
    """Return the first tick (row index) where LSTM reconstruction error > threshold."""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    X = scaler.transform(pd.DataFrame(rows)[FEATURES].fillna(0).values.astype(np.float32))
    model.eval()
    with torch.no_grad():
        for i in range(window - 1, len(X)):
            seq = torch.tensor(X[i - window + 1:i + 1], dtype=torch.float32).unsqueeze(0).to(device)
            err = ((model(seq) - seq) ** 2).mean().item()
            if err > threshold:
                return i
    return None


def _alarm_tick(rows: List[dict], fault: str) -> Optional[int]:
    """Return the first tick where the rule-based threshold alarm fires."""
    rule = ALARM_RULES.get(fault)
    if rule is None:
        return None
    for i, row in enumerate(rows):
        try:
            if rule(row):
                return i
        except Exception:
            pass
    return None


# ── Main experiment ───────────────────────────────────────────────────────────

def run_experiment(n_normal: int = 300, n_fault: int = 300,
                   window: int = 30, epochs: int = 30,
                   seed: int = 42) -> List[dict]:
    """Run the lead-time experiment for all fault classes."""
    print("Generating normal training data for LSTM …")
    random.seed(seed)
    r_ohm = max(0.25, random.gauss(0.4, 0.06))
    eta_f = random.uniform(0.90, 0.98)
    normal_rows = [_make_row(k, fault=None, r_ohm=r_ohm, eta_f=eta_f) for k in range(2000)]
    X_normal_df = pd.DataFrame(normal_rows)[FEATURES].fillna(0)

    scaler   = StandardScaler()
    X_normal = scaler.fit_transform(X_normal_df.values.astype(np.float32))

    print(f"Training LSTM Autoencoder ({epochs} epochs) …")
    model, threshold = _train_lstm(X_normal, window=window, epochs=epochs)
    print(f"  Anomaly threshold (μ+3σ): {threshold:.6f}\n")

    results = []
    for fault in FAULT_CLASSES:
        rows, labels = _generate_trace(fault, n_normal, n_fault, seed=seed + hash(fault) % 1000)
        fault_onset  = labels.index(1)   # first fault tick (= n_normal)

        t_lstm  = _detection_tick(model, scaler, rows, threshold, window)
        t_alarm = _alarm_tick(rows, fault)

        lstm_lead  = fault_onset if t_lstm is None else t_lstm
        alarm_lead = fault_onset if t_alarm is None else t_alarm

        lead_s = (
            (alarm_lead - lstm_lead)
            if t_lstm is not None and t_alarm is not None
            else None
        )

        result = {
            "fault":          fault,
            "fault_onset_s":  fault_onset,
            "lstm_detection_s":  t_lstm,
            "alarm_detection_s": t_alarm,
            "lead_time_s":    lead_s,
            "lstm_missed":    t_lstm is None,
            "alarm_missed":   t_alarm is None,
        }
        lead_str = f"{lead_s:+.0f} s" if lead_s is not None else "N/A"
        lstm_str = f"{t_lstm}" if t_lstm is not None else "MISSED"
        alarm_str = f"{t_alarm}" if t_alarm is not None else "MISSED"
        print(f"  {fault:<26}  onset={fault_onset}  LSTM={lstm_str:>6}  alarm={alarm_str:>6}  lead={lead_str}")
        results.append(result)

    return results


def plot_results(results: List[dict], out_dir: pathlib.Path) -> None:
    """Bar chart of lead times per fault class."""
    valid = [r for r in results if r["lead_time_s"] is not None]
    if not valid:
        print("No valid lead-time results to plot.")
        return

    faults    = [r["fault"].replace("_", "\n") for r in valid]
    lead_vals = [r["lead_time_s"] for r in valid]

    fig, ax = plt.subplots(figsize=(13, 6))
    colors = ["steelblue" if v >= 0 else "tomato" for v in lead_vals]
    bars = ax.bar(range(len(faults)), lead_vals, color=colors, edgecolor="white", linewidth=0.5)
    ax.axhline(0, color="black", lw=0.8, ls="--")
    ax.set_xticks(range(len(faults)))
    ax.set_xticklabels(faults, fontsize=8)
    ax.set_ylabel("Lead time (s)\n[positive = LSTM detected earlier]", fontsize=10)
    ax.set_title(
        "LSTM Autoencoder Early-Detection Lead Time vs. Threshold-Based Alarm\n"
        f"(N={len(results)} fault classes, 300 normal + 300 fault rows, 30-s window)",
        fontsize=11,
    )
    ax.grid(axis="y", alpha=0.3)
    for bar, val in zip(bars, lead_vals):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + (0.5 if val >= 0 else -1.5),
                f"{val:+.0f}s", ha="center", va="bottom", fontsize=7)
    plt.tight_layout()
    out = out_dir / "leadtime_comparison.png"
    plt.savefig(str(out), dpi=150)
    print(f"\nBar chart saved → {out}")
    plt.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="LSTM lead-time experiment")
    parser.add_argument("--rows",         type=int, default=300, help="Normal/fault rows each (default 300)")
    parser.add_argument("--window",       type=int, default=30,  help="LSTM window size in seconds (default 30)")
    parser.add_argument("--epochs",       type=int, default=30,  help="LSTM training epochs (default 30)")
    parser.add_argument("--seed",         type=int, default=42)
    parser.add_argument("--out",          default="data/leadtime_experiment.json")
    args = parser.parse_args()

    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print("=== LSTM Autoencoder Lead-Time Experiment ===\n")
    results = run_experiment(
        n_normal=args.rows, n_fault=args.rows,
        window=args.window, epochs=args.epochs, seed=args.seed,
    )

    # Summary statistics
    valid_leads = [r["lead_time_s"] for r in results if r["lead_time_s"] is not None]
    if valid_leads:
        print(f"\n=== Summary ({len(valid_leads)}/{len(results)} faults with measurable lead time) ===")
        print(f"  Mean lead time : {sum(valid_leads)/len(valid_leads):+.1f} s")
        print(f"  Min  lead time : {min(valid_leads):+.1f} s")
        print(f"  Max  lead time : {max(valid_leads):+.1f} s")
        print(f"  LSTM faster in : {sum(1 for v in valid_leads if v > 0)}/{len(valid_leads)} fault classes")

    out_path.write_text(json.dumps({"results": results, "summary": {
        "n_fault_classes":   len(results),
        "n_measurable":      len(valid_leads),
        "mean_lead_time_s":  round(sum(valid_leads) / len(valid_leads), 1) if valid_leads else None,
        "min_lead_time_s":   round(min(valid_leads), 1) if valid_leads else None,
        "max_lead_time_s":   round(max(valid_leads), 1) if valid_leads else None,
        "lstm_faster_count": sum(1 for v in valid_leads if v > 0),
    }}, indent=2))
    print(f"Results saved → {out_path}")

    plot_results(results, out_path.parent)


if __name__ == "__main__":
    main()

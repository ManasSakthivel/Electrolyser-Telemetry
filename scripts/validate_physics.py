#!/usr/bin/env python3
"""
validate_physics.py
===================
Validates the three-term Butler-Volmer physics model used by the electrolyser
digital twin against published PEM polarisation curve data.

Three-term model
----------------
  V_cell = U_rev + V_act + V_conc + R_ohm × I

  where:
    V_act  = (RT / αF)  × arcsinh(I / 2I₀)          [Butler-Volmer activation]
    V_conc = (RT / 2F)  × ln(I_lim / (I_lim − I))   [Nernst concentration]
    R_ohm × I                                          [Ohmic resistance]

Methodology
-----------
1.  Fits the three-term model to reference data (Monopoli et al. 2024 + NREL 2020)
    using scipy least-squares minimisation to obtain (R_OHM_ref, I0_ref, I_LIM_ref).
2.  Reports RMSE of the fitted three-term model on held-out Koch et al. [14] data
    (independent validation, not used during fitting).
3.  Compares three-term vs. Butler-Volmer-only vs. Ohmic-only to quantify the
    incremental contribution of the concentration overpotential term.
4.  Documents the simulation-scale parameters vs. reference-calibrated parameters.

References
----------
[1]  D. Monopoli et al., Annual Reviews in Control, vol. 57, p. 100943, 2024.
[2]  NREL, "PEM Electrolysis Stack Performance Characterisation", Tech. Rep., 2020.
[14] S. Koch, M. Papantonis, T. Hannemann, "Open dataset of PEM electrolyser
     polarisation curves under varying temperature and pressure",
     Data in Brief, vol. 52, p. 109938, 2024.

Output
------
    data/polarisation_curve_comparison.png
    data/physics_validation_report.json
"""

from __future__ import annotations

import json
import math
import pathlib
import sys
from typing import List, Tuple

import matplotlib.pyplot as plt
import numpy as np

try:
    from scipy.optimize import minimize
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "clients" / "python"))
import unittest.mock as _mock
_mock.patch.dict("sys.modules", {
    "paho": _mock.MagicMock(),
    "paho.mqtt": _mock.MagicMock(),
    "paho.mqtt.client": _mock.MagicMock(),
}).start()

from plant_sim import ALPHA, FARADAY, R_GAS, TANK_TEMP_K, U_REV  # noqa: E402

ROOT    = pathlib.Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data"
OUT_DIR.mkdir(exist_ok=True)

RT_aF  = R_GAS * TANK_TEMP_K / (ALPHA * FARADAY)   # ≈ 0.02569 V at 25 °C  (activation factor)
RT_2F  = R_GAS * TANK_TEMP_K / (2.0 * FARADAY)     # ≈ 0.01285 V at 25 °C  (concentration factor)

# ── Reference-calibrated parameters ──────────────────────────────────────────
# Grid-optimised to minimise joint RMSE on Monopoli et al. 2024 + NREL 2020.
# These represent a real 25 cm² PEM cell at 25 °C, 1 atm and are NOT the
# simulation's toy parameters (which are scaled for fault signature diversity).
R_OHM_REF: float = 0.220   # Ω/cell  (fitted to reference data)
I0_REF:    float = 0.010   # A       (fitted exchange current density)
I_LIM_REF: float = 4.0     # A       (fitted limiting current density — mass transport)

# ── Reference training data (Monopoli et al. 2024 + NREL 2020) ───────────────
MONOPOLI_REFERENCE: List[Tuple[float, float]] = [
    (0.0, 1.23), (0.2, 1.48), (0.4, 1.56), (0.6, 1.62), (0.8, 1.67),
    (1.0, 1.72), (1.2, 1.76), (1.4, 1.80), (1.6, 1.84), (1.8, 1.88),
    (2.0, 1.92), (2.2, 1.97), (2.4, 2.02), (2.6, 2.08), (2.8, 2.14),
    (3.0, 2.21),
]
NREL_REFERENCE: List[Tuple[float, float]] = [
    (0.5, 1.58), (1.0, 1.71), (1.5, 1.82), (2.0, 1.94), (2.5, 2.07),
]

# ── Koch et al. 2024 independent validation data ──────────────────────────────
# Digitised from Koch, Papantonis, Hannemann, Data in Brief, vol. 52, 2024.
# Cell: 25 cm² MEA, Nafion 117, 25 °C, 1 bar abs — INDEPENDENT of training data.
KOCH_REFERENCE: List[Tuple[float, float]] = [
    (0.3, 1.52), (0.6, 1.61), (0.9, 1.69), (1.2, 1.76),
    (1.5, 1.83), (1.8, 1.90), (2.1, 1.98), (2.4, 2.07),
    (2.7, 2.18), (3.0, 2.31),
]


# ── Model functions ───────────────────────────────────────────────────────────

def bv_ohmic_three_term(
    i: float,
    r_ohm: float = R_OHM_REF,
    i0: float    = I0_REF,
    i_lim: float = I_LIM_REF,
) -> float:
    """Three-term per-cell voltage: activation + concentration + Ohmic."""
    if i <= 0.0:
        return U_REV
    v_act  = RT_aF * math.asinh(i / (2.0 * i0))
    margin = max(i_lim - i, 1e-6)
    v_conc = RT_2F * math.log(i_lim / margin)
    return U_REV + v_act + v_conc + r_ohm * i


def bv_ohmic_two_term(
    i: float,
    r_ohm: float = R_OHM_REF,
    i0: float    = I0_REF,
) -> float:
    """Two-term per-cell voltage: activation + Ohmic (no concentration term)."""
    if i <= 0.0:
        return U_REV
    return U_REV + RT_aF * math.asinh(i / (2.0 * i0)) + r_ohm * i


def ohmic_only(i: float, r_ohm: float = R_OHM_REF) -> float:
    """Ohmic-only per-cell voltage (baseline model)."""
    return U_REV + r_ohm * i


def rmse(ref: List[Tuple[float, float]], fn) -> float:
    return math.sqrt(sum((fn(i) - v) ** 2 for i, v in ref) / len(ref))


# ── Parameter fitting ─────────────────────────────────────────────────────────

def fit_parameters(
    ref_data: List[Tuple[float, float]],
) -> Tuple[float, float, float]:
    """
    Fit (R_ohm, I0, I_lim) to minimise RMSE on ref_data using scipy.
    Falls back to the hard-coded reference values if scipy is unavailable.
    """
    if not HAS_SCIPY:
        print("  [scipy not available — using pre-fitted reference parameters]")
        return R_OHM_REF, I0_REF, I_LIM_REF

    currents = np.array([i for i, _ in ref_data])
    voltages = np.array([v for _, v in ref_data])

    def residuals(params: np.ndarray) -> float:
        r_ohm, log_i0, log_ilim = params
        i0    = math.exp(log_i0)
        i_lim = math.exp(log_ilim)
        preds = np.array([bv_ohmic_three_term(i, r_ohm, i0, i_lim) for i in currents])
        return float(np.mean((preds - voltages) ** 2))

    x0 = [R_OHM_REF, math.log(I0_REF), math.log(I_LIM_REF)]
    bounds = [(0.05, 0.8), (math.log(1e-5), math.log(1.0)), (math.log(2.0), math.log(10.0))]
    result = minimize(residuals, x0, method="L-BFGS-B", bounds=bounds,
                      options={"maxiter": 2000, "ftol": 1e-14})
    r_ohm_fit = result.x[0]
    i0_fit    = math.exp(result.x[1])
    i_lim_fit = math.exp(result.x[2])
    return r_ohm_fit, i0_fit, i_lim_fit


# ── Plot ──────────────────────────────────────────────────────────────────────

def plot_comparison(r_ohm: float, i0: float, i_lim: float) -> dict:
    currents = np.linspace(0, 3.2, 400)

    v_three = np.array([bv_ohmic_three_term(i, r_ohm, i0, i_lim) for i in currents])
    v_two   = np.array([bv_ohmic_two_term(i, r_ohm, i0) for i in currents])
    v_ohm   = np.array([ohmic_only(i, r_ohm) for i in currents])

    # RMSE on training reference (Monopoli + NREL)
    fn3 = lambda i: bv_ohmic_three_term(i, r_ohm, i0, i_lim)  # noqa: E731
    fn2 = lambda i: bv_ohmic_two_term(i, r_ohm, i0)            # noqa: E731
    fn1 = lambda i: ohmic_only(i, r_ohm)                       # noqa: E731

    rmse_3_mono = rmse(MONOPOLI_REFERENCE, fn3)
    rmse_3_nrel = rmse(NREL_REFERENCE,     fn3)
    rmse_2_mono = rmse(MONOPOLI_REFERENCE, fn2)
    rmse_1_mono = rmse(MONOPOLI_REFERENCE, fn1)

    # RMSE on Koch et al. — independent validation (not used during fitting)
    rmse_3_koch = rmse(KOCH_REFERENCE, fn3)

    fig, ax = plt.subplots(figsize=(10, 7))
    ax.plot(currents, v_three, color="steelblue",  lw=2.5,
            label=f"Three-term BV + Conc + Ohmic  RMSE={rmse_3_mono:.4f} V (Monopoli)")
    ax.plot(currents, v_two,   color="darkorange",  lw=1.8, ls="-.",
            label=f"Two-term BV + Ohmic            RMSE={rmse_2_mono:.4f} V (Monopoli)")
    ax.plot(currents, v_ohm,   color="grey",         lw=1.5, ls="--",
            label=f"Ohmic-only                     RMSE={rmse_1_mono:.4f} V (Monopoli)")

    ref_i, ref_v = zip(*MONOPOLI_REFERENCE)
    ax.scatter(ref_i, ref_v, marker="o", s=60, color="steelblue", zorder=5,
               label="Monopoli et al. 2024 [1] — training")
    nrel_i, nrel_v = zip(*NREL_REFERENCE)
    ax.scatter(nrel_i, nrel_v, marker="s", s=60, color="green", zorder=5,
               label="NREL 2020 [2] — training")
    koch_i, koch_v = zip(*KOCH_REFERENCE)
    ax.scatter(koch_i, koch_v, marker="^", s=70, color="crimson", zorder=5,
               label=f"Koch et al. 2024 [14] — independent validation  RMSE={rmse_3_koch:.4f} V")

    ax.set_xlabel("Stack Current (A)", fontsize=12)
    ax.set_ylabel("Per-Cell Voltage (V)", fontsize=12)
    ax.set_title(
        "PEM Polarisation Curve — Three-Term Model vs. Published Data\n"
        f"Fitted: R_ohm={r_ohm:.3f} Ω, I₀={i0:.4f} A, I_lim={i_lim:.2f} A, α={ALPHA}, T={TANK_TEMP_K} K",
        fontsize=10,
    )
    ax.legend(fontsize=8.5)
    ax.set_xlim(0, 3.3)
    ax.set_ylim(1.1, 2.5)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    out = OUT_DIR / "polarisation_curve_comparison.png"
    plt.savefig(str(out), dpi=150)
    print(f"Figure saved → {out}")
    plt.close()

    return {
        "model_form":   "V = U_rev + (RT/αF)·arcsinh(I/2I₀) + (RT/2F)·ln(I_lim/(I_lim−I)) + R_ohm·I",
        "fitted_params": {
            "U_rev_V": U_REV, "R_ohm_ref_Ohm": round(r_ohm, 4),
            "I0_ref_A": round(i0, 6), "I_lim_ref_A": round(i_lim, 4),
            "alpha": ALPHA, "T_K": TANK_TEMP_K,
        },
        "sim_params_note": "Simulation uses toy-scale parameters for fault signature diversity.",
        "rmse_three_term": {
            "vs_monopoli_2024_V": round(rmse_3_mono, 5),
            "vs_nrel_2020_V":     round(rmse_3_nrel, 5),
            "vs_koch_2024_V":     round(rmse_3_koch, 5),
        },
        "rmse_two_term_vs_monopoli_V":   round(rmse_2_mono, 5),
        "rmse_ohmic_only_vs_monopoli_V": round(rmse_1_mono, 5),
        "three_vs_two_term_improvement_pct":  round((1 - rmse_3_mono / rmse_2_mono) * 100, 1),
        "bv_vs_ohmic_improvement_pct":        round((1 - rmse_2_mono / rmse_1_mono) * 100, 1),
        "three_vs_ohmic_improvement_pct":     round((1 - rmse_3_mono / rmse_1_mono) * 100, 1),
    }


def main() -> None:
    print("=== Physics Validation — PEM Polarisation Curve (Three-Term Model) ===\n")
    print("Step 1: Fitting parameters to Monopoli et al. 2024 + NREL 2020 …")
    training_data = MONOPOLI_REFERENCE + NREL_REFERENCE
    r_ohm, i0, i_lim = fit_parameters(training_data)
    print(f"  Fitted R_ohm = {r_ohm:.4f} Ω   I₀ = {i0:.6f} A   I_lim = {i_lim:.4f} A\n")

    print("Step 2: Evaluating on independent Koch et al. 2024 dataset …")
    report = plot_comparison(r_ohm, i0, i_lim)

    print("\n=== Results ===")
    print(f"Three-term model RMSE vs Monopoli et al. 2024 :  {report['rmse_three_term']['vs_monopoli_2024_V']:.5f} V")
    print(f"Three-term model RMSE vs NREL 2020            :  {report['rmse_three_term']['vs_nrel_2020_V']:.5f} V")
    print(f"Three-term model RMSE vs Koch et al. 2024     :  {report['rmse_three_term']['vs_koch_2024_V']:.5f} V  ← independent validation")
    print(f"Two-term (BV+Ohmic) RMSE vs Monopoli          :  {report['rmse_two_term_vs_monopoli_V']:.5f} V")
    print(f"Ohmic-only RMSE vs Monopoli                   :  {report['rmse_ohmic_only_vs_monopoli_V']:.5f} V")
    print(f"\nConc. term improvement (3-term vs 2-term)     :  {report['three_vs_two_term_improvement_pct']:.1f}%")
    print(f"BV improvement (2-term vs ohmic-only)         :  {report['bv_vs_ohmic_improvement_pct']:.1f}%")
    print(f"Total improvement (3-term vs ohmic-only)      :  {report['three_vs_ohmic_improvement_pct']:.1f}%")

    out = OUT_DIR / "physics_validation_report.json"
    out.write_text(json.dumps(report, indent=2))
    print(f"\nReport saved → {out}")


if __name__ == "__main__":
    main()

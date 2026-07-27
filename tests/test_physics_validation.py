"""
tests/test_physics_validation.py
=================================
Validates the Butler-Volmer model form against published PEM reference data
using reference-calibrated parameters (see scripts/validate_physics.py).

All tests run without a live broker or network access.
"""

from __future__ import annotations

import math
import pathlib
import sys
import unittest.mock as _mock

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "clients" / "python"))
_mock.patch.dict("sys.modules", {
    "paho": _mock.MagicMock(),
    "paho.mqtt": _mock.MagicMock(),
    "paho.mqtt.client": _mock.MagicMock(),
}).start()

from plant_sim import ALPHA, FARADAY, R_GAS, TANK_TEMP_K, U_REV  # noqa: E402

# ── Reference-calibrated parameters (same as validate_physics.py) ─────────────
# Grid-optimised to minimise RMSE across both Monopoli et al. and NREL datasets.
RT_aF      = R_GAS * TANK_TEMP_K / (ALPHA * FARADAY)
R_OHM_REF  = 0.220   # Ω (fitted to reference data)
I0_REF     = 0.010   # A (fitted exchange current density)

# ── Reference data (Monopoli et al. 2024, NREL 2020) ─────────────────────────
MONOPOLI_REF = [
    (0.2, 1.48), (0.6, 1.62), (1.0, 1.72),
    (1.4, 1.80), (1.8, 1.88), (2.2, 1.97),
    (2.6, 2.08), (3.0, 2.21),
]
NREL_REF = [
    (0.5, 1.58), (1.0, 1.71), (1.5, 1.82),
    (2.0, 1.94), (2.5, 2.07),
]


def bv_ohmic(i: float) -> float:
    """Butler-Volmer + Ohmic cell voltage using reference-calibrated parameters."""
    if i <= 0.0:
        return U_REV
    return U_REV + RT_aF * math.asinh(i / (2.0 * I0_REF)) + R_OHM_REF * i


def ohmic_only(i: float) -> float:
    return U_REV + R_OHM_REF * i


def rmse(ref, fn) -> float:
    return math.sqrt(sum((fn(i) - v) ** 2 for i, v in ref) / len(ref))


class TestPolarisationCurve:
    def test_rmse_vs_monopoli_below_threshold(self):
        """Butler-Volmer + Ohmic RMSE vs. Monopoli et al. must be < 0.04 V."""
        err = rmse(MONOPOLI_REF, bv_ohmic)
        assert err < 0.04, f"RMSE vs Monopoli = {err:.4f} V (threshold 0.04 V)"

    def test_rmse_vs_nrel_below_threshold(self):
        """Butler-Volmer + Ohmic RMSE vs. NREL benchmark must be < 0.04 V."""
        err = rmse(NREL_REF, bv_ohmic)
        assert err < 0.04, f"RMSE vs NREL = {err:.4f} V (threshold 0.04 V)"

    def test_butler_volmer_beats_ohmic_only(self):
        """BV model must have lower RMSE than Ohmic-only on both reference sets."""
        for ref_name, ref in [("Monopoli", MONOPOLI_REF), ("NREL", NREL_REF)]:
            assert rmse(ref, bv_ohmic) < rmse(ref, ohmic_only), \
                f"BV should beat Ohmic-only on {ref_name}"

    def test_open_circuit_voltage_at_zero_current(self):
        """At I=0 the cell voltage should equal U_rev (reversible potential)."""
        assert bv_ohmic(0.0) == pytest.approx(U_REV, abs=1e-6)

    def test_voltage_monotonically_increases_with_current(self):
        """Polarisation curve must be monotonically increasing from 0 to 3 A."""
        currents = [i * 0.1 for i in range(31)]
        voltages = [bv_ohmic(i) for i in currents]
        for i in range(len(voltages) - 1):
            assert voltages[i+1] >= voltages[i], \
                f"Non-monotonic at I={currents[i+1]:.1f} A"


class TestTelemetryTypes:
    """Tests for the typed dataclass payload contract."""

    def test_from_dict_valid(self):
        import sys
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "clients" / "python"))
        from telemetry_types import TelemetryPayload, TelemetryMetrics, TelemetryQuality
        p = TelemetryPayload.from_dict({
            "ts": "2025-01-01T00:00:00Z",
            "site_id": "rvce-plant-A",
            "stack_id": "EL1",
            "sensor_id": "cell_1_voltage",
            "cell": 1,
            "metrics": {"value": 1.95, "unit": "V"},
            "quality": {"qos": 1, "status": "OK", "seq": 42},
        })
        assert p.metrics.value == pytest.approx(1.95)
        assert p.quality.status == "OK"
        assert p.cell == 1

    def test_from_dict_missing_field_raises(self):
        import sys
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "clients" / "python"))
        from telemetry_types import TelemetryPayload
        with pytest.raises(KeyError):
            TelemetryPayload.from_dict({
                "ts": "2025-01-01T00:00:00Z",
                # site_id intentionally missing
                "stack_id": "EL1",
                "sensor_id": "stack_current",
                "metrics": {"value": 1.8, "unit": "A"},
                "quality": {"qos": 1, "status": "OK", "seq": 0},
            })

    def test_invalid_qos_raises(self):
        import sys
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "clients" / "python"))
        from telemetry_types import TelemetryQuality
        with pytest.raises(ValueError):
            TelemetryQuality(qos=5, status="OK", seq=0)

    def test_to_feature_row_keys(self):
        import sys
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "clients" / "python"))
        from telemetry_types import TelemetryPayload
        p = TelemetryPayload.from_dict({
            "ts": "2025-01-01T00:00:00Z",
            "site_id": "rvce-plant-A",
            "stack_id": "EL1",
            "sensor_id": "h2_flow_rate",
            "metrics": {"value": 0.40, "unit": "L/min"},
            "quality": {"qos": 1, "status": "OK", "seq": 99},
        })
        row = p.to_feature_row()
        assert set(row.keys()) == {
            "ts", "site_id", "stack_id", "sensor_id", "cell",
            "value", "unit", "qos", "status", "seq", "fault_active"
        }

"""
tests/test_physics.py
=====================
Unit tests for the electrolyser digital-twin physics and fault-injection logic.
All tests run without a live MQTT broker.
"""

from __future__ import annotations

import json
import math
import pathlib
import sys

import pytest

# ── Make the clients module importable without installing ─────────────────────
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "clients" / "python"))

# Patch paho so we can import plant_sim without needing it installed during CI
import unittest.mock as mock
sys.modules.setdefault("paho", mock.MagicMock())
sys.modules.setdefault("paho.mqtt", mock.MagicMock())
sys.modules.setdefault("paho.mqtt.client", mock.MagicMock())

from plant_sim import (  # noqa: E402  (import after mock patch)
    ALPHA,
    ATM_PA,
    FARADAY,
    FAULT_CELL_DRYOUT,
    FAULT_CELL_FLOODING,
    FAULT_DCDC_FAILURE,
    FAULT_GAS_CROSSOVER,
    FAULT_LOOSE_BOLT,
    FAULT_MEMBRANE_PINHOLE,
    FAULT_NAMES,
    FAULT_O2_BLOCKAGE,
    FAULT_OVER_PRESSURE,
    FAULT_PUMP_FAILURE,
    FAULT_TELEMETRY_DROPOUT,
    FAULT_VOLTAGE_SENSOR_DRIFT,
    I_LIM,
    I_REF,
    N_CELLS,
    R_GAS,
    TANK_TEMP_K,
    TANK_VOLUME_M3,
    U_REV,
    ElectrolyserTwin,
    FaultInjector,
    _activation_overpotential,
    _concentration_overpotential,
)

from sensor_client import generate_value, resolve_topic  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════════════
# Physics helpers
# ═══════════════════════════════════════════════════════════════════════════════

class TestActivationOverpotential:
    def test_zero_current_returns_zero(self):
        assert _activation_overpotential(0.0) == 0.0

    def test_negative_current_returns_zero(self):
        assert _activation_overpotential(-1.0) == 0.0

    def test_positive_current_returns_positive(self):
        v = _activation_overpotential(1.8)
        assert v > 0.0

    def test_activation_increases_monotonically(self):
        v1 = _activation_overpotential(0.5)
        v2 = _activation_overpotential(1.0)
        v3 = _activation_overpotential(2.0)
        assert v1 < v2 < v3

    def test_formula_correct(self):
        """V_act = (RT/αF) × arcsinh(I/2I₀)"""
        from plant_sim import I0
        i = 1.8
        expected = (R_GAS * TANK_TEMP_K / (ALPHA * FARADAY)) * math.asinh(i / (2.0 * I0))
        assert abs(_activation_overpotential(i) - expected) < 1e-12

    def test_butler_volmer_raises_voltage_above_ohmic_only(self):
        """Stack voltage with BV must exceed the Ohmic-only model."""
        from plant_sim import R_OHM
        i = 1.8
        v_ohmic_only = N_CELLS * (U_REV + R_OHM * i)
        twin = ElectrolyserTwin.__new__(ElectrolyserTwin)
        twin.N = N_CELLS
        twin.U_rev = U_REV
        v_act = _activation_overpotential(i)
        v_bv = N_CELLS * (U_REV + v_act + R_OHM * i)
        assert v_bv > v_ohmic_only


# ═══════════════════════════════════════════════════════════════════════════════
# Concentration overpotential
# ═══════════════════════════════════════════════════════════════════════════════

class TestConcentrationOverpotential:
    def test_zero_current_returns_zero(self):
        assert _concentration_overpotential(0.0) == 0.0

    def test_negative_current_returns_zero(self):
        assert _concentration_overpotential(-1.0) == 0.0

    def test_positive_current_returns_positive(self):
        v = _concentration_overpotential(1.0)
        assert v > 0.0

    def test_increases_monotonically_with_current(self):
        v1 = _concentration_overpotential(0.5)
        v2 = _concentration_overpotential(1.0)
        v3 = _concentration_overpotential(2.0)
        assert v1 < v2 < v3

    def test_formula_correct(self):
        """V_conc = (RT/2F) × ln(I_lim / (I_lim − I))"""
        i = 1.5
        rt_2f = R_GAS * TANK_TEMP_K / (2.0 * FARADAY)
        import math
        expected = rt_2f * math.log(I_LIM / max(I_LIM - i, 1e-6))
        assert abs(_concentration_overpotential(i) - expected) < 1e-12

    def test_three_term_exceeds_two_term(self):
        """Three-term voltage must exceed two-term (BV+Ohmic) at same current."""
        from plant_sim import R_OHM
        i = 1.8
        v_act  = _activation_overpotential(i)
        v_conc = _concentration_overpotential(i)
        v_two   = N_CELLS * (U_REV + v_act + R_OHM * i)
        v_three = N_CELLS * (U_REV + v_act + v_conc + R_OHM * i)
        assert v_three > v_two

    def test_approaches_i_lim_produces_large_penalty(self):
        """As current approaches I_lim, concentration penalty must be significantly
        larger than at mid-range current — verifying the logarithmic divergence."""
        i_near_lim = I_LIM * 0.99
        v_conc = _concentration_overpotential(i_near_lim)
        v_mid  = _concentration_overpotential(I_LIM * 0.5)
        # At 99% I_lim: ln(I_lim / 0.01*I_lim) = ln(100) ≈ 4.6
        # At 50% I_lim: ln(I_lim / 0.5*I_lim) = ln(2) ≈ 0.69
        # Ratio ≈ 6.6 — use 5x as a conservative bound
        assert v_conc > 5 * v_mid


# ═══════════════════════════════════════════════════════════════════════════════
# FaultInjector
# ═══════════════════════════════════════════════════════════════════════════════

class TestFaultInjector:
    def test_activate_and_is_active(self):
        fi = FaultInjector()
        fi.set_fault("membrane_pinhole", True)
        assert fi.is_active(FAULT_MEMBRANE_PINHOLE)

    def test_deactivate(self):
        fi = FaultInjector()
        fi.set_fault("pump_failure", True)
        fi.set_fault("pump_failure", False)
        assert not fi.is_active(FAULT_PUMP_FAILURE)

    def test_unknown_fault_ignored(self):
        fi = FaultInjector()
        fi.set_fault("nonexistent_fault")  # should not raise
        assert len(fi.active_names()) == 0

    def test_clear_all(self):
        fi = FaultInjector()
        fi.set_fault("cell_dryout")
        fi.set_fault("gas_crossover")
        fi.clear_all()
        assert fi.active_names() == []

    def test_active_names_returns_correct_labels(self):
        fi = FaultInjector()
        fi.set_fault("over_pressure")
        fi.set_fault("loose_bolt")
        names = fi.active_names()
        assert "over_pressure" in names
        assert "loose_bolt"    in names

    def test_all_fault_names_registered(self):
        """Every constant in FAULT_NAMES must correspond to a valid int."""
        for name, fid in FAULT_NAMES.items():
            assert isinstance(fid, int), f"{name} should map to int"


# ═══════════════════════════════════════════════════════════════════════════════
# ElectrolyserTwin state transitions
# ═══════════════════════════════════════════════════════════════════════════════

def _make_twin() -> ElectrolyserTwin:
    """Return an ElectrolyserTwin with MQTT clients pre-stubbed."""
    twin = ElectrolyserTwin("EL1")
    twin.clients = {}   # no real MQTT
    return twin


class TestTwinPhysics:
    def test_normal_run_increases_tank_pressure(self):
        """After sustained operation at high irradiance, H₂ accumulates in the tank.

        We assert on tank_moles (physical quantity, monotonically increasing) rather
        than tank_pressure_bar which is multiplied by a ±0.5% noise term each step.
        """
        twin = _make_twin()
        n_before = twin.tank_moles
        for _ in range(20):
            twin.update_from_pv(800.0, 1.0)
        assert twin.tank_moles > n_before, (
            f"tank_moles should increase during sustained electrolysis; "
            f"before={n_before:.6f}  after={twin.tank_moles:.6f}"
        )

    def test_zero_irradiance_drives_current_to_zero(self):
        twin = _make_twin()
        for _ in range(20):
            twin.update_from_pv(0.0, 1.0)
        assert twin.I_stack < 0.1

    def test_high_irradiance_approaches_i_ref(self):
        twin = _make_twin()
        for _ in range(30):
            twin.update_from_pv(1000.0, 1.0)
        assert abs(twin.I_stack - I_REF) < 0.5

    def test_cell_voltage_count(self):
        twin = _make_twin()
        twin.update_from_pv(800.0, 1.0)
        assert len(twin.cell_voltages) == N_CELLS


class TestTwinFaultEffects:
    def test_membrane_pinhole_raises_cell_0_voltage(self):
        twin = _make_twin()
        twin.fault_injector.set_fault("membrane_pinhole")
        for _ in range(5):
            twin.update_from_pv(800.0, 1.0)
        assert twin.cell_voltages[0] > twin.cell_voltages[2] + 0.1

    def test_gas_crossover_changes_ratio(self):
        twin = _make_twin()
        twin.fault_injector.set_fault("gas_crossover")
        twin.update_from_pv(800.0, 1.0)
        if twin.o2_flow_Lpm > 0:
            ratio = twin.h2_flow_Lpm / twin.o2_flow_Lpm
            assert ratio > 2.1 or ratio < 1.9

    def test_cell_flooding_drops_cells_3_4(self):
        twin = _make_twin()
        twin.fault_injector.set_fault("cell_flooding")
        twin.update_from_pv(800.0, 1.0)
        assert twin.cell_voltages[2] < 1.4
        assert twin.cell_voltages[3] < 1.4

    def test_pump_failure_zeros_water_flow(self):
        twin = _make_twin()
        twin.fault_injector.set_fault("pump_failure")
        twin.update_from_pv(800.0, 1.0)
        assert twin.water_flow == 0.0

    def test_dcdc_failure_zeros_current(self):
        twin = _make_twin()
        twin.fault_injector.set_fault("dcdc_failure")
        twin.update_from_pv(1000.0, 1.0)
        assert twin.I_stack == 0.0

    def test_over_pressure_spikes_tank(self):
        twin = _make_twin()
        twin.fault_injector.set_fault("over_pressure")
        twin.update_from_pv(800.0, 1.0)
        assert twin.tank_pressure_bar == pytest.approx(40.0)

    def test_voltage_sensor_drift_sticks_cell5(self):
        twin = _make_twin()
        twin.fault_injector.set_fault("voltage_sensor_drift")
        twin.update_from_pv(800.0, 1.0)
        assert twin.cell_voltages[4] == pytest.approx(0.0)

    def test_telemetry_dropout_publish_skipped(self):
        """publish_all() returns early under telemetry dropout — no clients called."""
        twin = _make_twin()
        published = []

        import unittest.mock as m
        with m.patch("plant_sim._publish_json", side_effect=lambda *a: published.append(a)):
            twin.fault_injector.set_fault("telemetry_dropout")
            twin.publish_all()

        assert len(published) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Telemetry schema
# ═══════════════════════════════════════════════════════════════════════════════

class TestTelemetrySchema:
    SCHEMA_PATH = pathlib.Path(__file__).resolve().parents[1] / "schemas" / "telemetry_v1.json"

    def _schema(self):
        from jsonschema import validate
        return json.loads(self.SCHEMA_PATH.read_text()), validate

    def test_schema_file_exists(self):
        assert self.SCHEMA_PATH.exists(), "schemas/telemetry_v1.json is missing"

    def test_minimal_valid_payload(self):
        import datetime
        schema, validate = self._schema()
        payload = {
            "ts":        datetime.datetime.utcnow().isoformat() + "Z",
            "site_id":   "rvce-plant-A",
            "stack_id":  "EL1",
            "sensor_id": "cell_1_voltage",
            "cell":      1,
            "metrics":   {"value": 1.95, "unit": "V"},
            "quality":   {"qos": 1, "status": "OK", "seq": 42},
        }
        validate(payload, schema)  # raises jsonschema.ValidationError on failure

    def test_missing_required_field_fails(self):
        from jsonschema import ValidationError
        schema, validate = self._schema()
        bad = {
            "ts": "2025-01-01T00:00:00Z",
            # site_id missing
            "stack_id":  "EL1",
            "sensor_id": "tank_pressure",
            "metrics":   {"value": 12.0, "unit": "bar"},
            "quality":   {"qos": 1, "status": "OK", "seq": 0},
        }
        with pytest.raises(ValidationError):
            validate(bad, schema)

    def test_invalid_qos_fails(self):
        from jsonschema import ValidationError
        schema, validate = self._schema()
        bad = {
            "ts": "2025-01-01T00:00:00Z",
            "site_id":   "rvce-plant-A",
            "stack_id":  "EL1",
            "sensor_id": "stack_current",
            "metrics":   {"value": 1.8, "unit": "A"},
            "quality":   {"qos": 5, "status": "OK", "seq": 0},  # invalid QoS
        }
        with pytest.raises(ValidationError):
            validate(bad, schema)

    def test_invalid_status_fails(self):
        from jsonschema import ValidationError
        schema, validate = self._schema()
        bad = {
            "ts": "2025-01-01T00:00:00Z",
            "site_id":   "rvce-plant-A",
            "stack_id":  "EL1",
            "sensor_id": "stack_current",
            "metrics":   {"value": 1.8, "unit": "A"},
            "quality":   {"qos": 1, "status": "UNKNOWN", "seq": 0},  # invalid enum
        }
        with pytest.raises(ValidationError):
            validate(bad, schema)


# ═══════════════════════════════════════════════════════════════════════════════
# sensor_client helpers
# ═══════════════════════════════════════════════════════════════════════════════

class TestSensorClientHelpers:
    def test_resolve_cell_topic(self):
        t = resolve_topic("EL1", "cell_1_voltage", cell=1)
        assert t == "electrolyser/plant-A/EL1/cell/1/voltage"

    def test_resolve_stack_current(self):
        t = resolve_topic("EL2", "stack_current")
        assert t == "electrolyser/plant-A/EL2/stack/current"

    def test_resolve_h2_flow(self):
        t = resolve_topic("EL1", "h2_flow_rate")
        assert t == "electrolyser/plant-A/EL1/h2/flow_rate"

    def test_resolve_tank_pressure(self):
        t = resolve_topic("EL1", "tank_pressure")
        assert t == "electrolyser/plant-A/EL1/tank/pressure"

    def test_resolve_irradiance(self):
        t = resolve_topic("PLANT", "irradiance_1")
        assert t == "electrolyser/plant-A/irradiance/1"

    def test_generate_cell_voltage_in_range(self):
        for _ in range(50):
            v = generate_value("EL1", "cell_1_voltage")
            assert 1.8 <= v <= 2.2

    def test_generate_stack_current_in_range(self):
        for _ in range(50):
            v = generate_value("EL1", "stack_current")
            assert 1.5 <= v <= 2.1

    def test_generate_irradiance_in_range(self):
        for _ in range(50):
            v = generate_value("PLANT", "irradiance_1")
            assert 0.0 <= v <= 1000.0

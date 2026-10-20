"""
tests/test_timeseries_and_inference.py
======================================
Deterministic integration and regression tests for Phase 3:
1. Real-time ML Inference Engine & 23-feature contract enforcement.
2. Anomaly scoring, safety alarm thresholds, and fault signature classification.
3. TelemetryConsumer integration with RealTimeInferenceEngine.
4. InfluxDB / Telegraf time-series ingestion field mapping.
5. Missing channels, NaN values, and error-handling status codes.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

CLIENTS_DIR = pathlib.Path(__file__).resolve().parents[1] / "clients" / "python"
if str(CLIENTS_DIR) not in sys.path:
    sys.path.insert(0, str(CLIENTS_DIR))

from realtime_inference import (
    ALL_FEATURES,
    ENGINEERED_FEATURES,
    RAW_FEATURES,
    RealTimeInferenceEngine,
    engineer_features_dict,
)
from telemetry_consumer import TelemetryConsumer

ROOT = pathlib.Path(__file__).resolve().parents[1]


# ═══════════════════════════════════════════════════════════════════════════════
# 1. 23-Feature Contract and Feature Engineering Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestFeatureContractAndEngineering:
    """Verifies strict 23-feature mathematical contracts matching notebooks and scripts."""

    def test_feature_constants_counts(self):
        assert len(RAW_FEATURES) == 14
        assert len(ENGINEERED_FEATURES) == 9
        assert len(ALL_FEATURES) == 23
        assert len(set(ALL_FEATURES)) == 23  # No duplicate feature names

    def test_engineer_features_dict_calculation(self):
        raw_data = {
            "cell_1_voltage": 1.95,
            "cell_2_voltage": 1.96,
            "cell_3_voltage": 1.94,
            "cell_4_voltage": 1.95,
            "cell_5_voltage": 1.97,
            "stack_current": 2.0,
            "stack_temperature": 50.0,
            "stack_pressure": 1.2,
            "h2_flow_rate": 0.40,
            "o2_flow_rate": 0.20,
            "tank_pressure": 15.0,
            "water_flow": 1.0,
            "irradiance_1": 800.0,
            "irradiance_2": 800.0,
        }

        feats = engineer_features_dict(raw_data)

        # Check that all 23 features are present
        for feat in ALL_FEATURES:
            assert feat in feats

        # Check mathematical correctness
        assert feats["cell_voltage_max"] == 1.97
        assert feats["cell_voltage_min"] == 1.94
        assert feats["cell_voltage_range"] == pytest.approx(0.03, abs=1e-4)
        assert feats["h2_o2_ratio"] == pytest.approx(2.0, abs=1e-3)
        assert feats["faradaic_efficiency"] == pytest.approx(0.40 / 2.0, abs=1e-3)
        assert feats["stack_power"] == pytest.approx(2.0 * 1.97 * 5.0, abs=1e-3)
        assert feats["thermal_load"] == pytest.approx(50.0 / (1.0 + 1e-3), abs=1e-2)
        assert feats["tank_fill_proxy"] == pytest.approx(15.0 * 0.40, abs=1e-3)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. RealTimeInferenceEngine Anomaly Detection & Fault Signatures
# ═══════════════════════════════════════════════════════════════════════════════

class TestRealTimeInferenceEngine:
    """Verifies anomaly detection, confidence, status, and fault signature mapping."""

    @pytest.fixture
    def nominal_raw(self) -> dict[str, float]:
        return {
            "cell_1_voltage": 1.95,
            "cell_2_voltage": 1.95,
            "cell_3_voltage": 1.95,
            "cell_4_voltage": 1.95,
            "cell_5_voltage": 1.95,
            "stack_current": 1.8,
            "stack_temperature": 45.0,
            "stack_pressure": 1.2,
            "h2_flow_rate": 0.40,
            "o2_flow_rate": 0.20,
            "tank_pressure": 15.0,
            "water_flow": 1.0,
            "irradiance_1": 750.0,
            "irradiance_2": 750.0,
        }

    def test_nominal_inference_healthy(self, nominal_raw):
        engine = RealTimeInferenceEngine(anomaly_threshold=0.65)
        res = engine.predict("EL1", nominal_raw)

        assert res.stack_id == "EL1"
        assert res.status == "HEALTHY"
        assert res.is_anomaly is False
        assert res.anomaly_score < 0.65
        assert res.predicted_fault == "normal"
        assert res.alarm_tripped is False
        assert len(res.trip_reasons) == 0

    def test_model_unavailable_status(self, nominal_raw):
        engine = RealTimeInferenceEngine(model_ready=False)
        res = engine.predict("EL1", nominal_raw)
        assert res.status == "MODEL_UNAVAILABLE"
        assert res.is_anomaly is False
        assert res.anomaly_score == 0.0

    def test_stale_telemetry_status(self, nominal_raw):
        engine = RealTimeInferenceEngine()
        res = engine.predict("EL1", nominal_raw, is_stale=True)
        assert res.status == "STALE"
        assert res.is_anomaly is False
        assert "stale" in res.trip_reasons[0].lower()

    def test_missing_channels_insufficient_data(self, nominal_raw):
        engine = RealTimeInferenceEngine()
        incomplete = nominal_raw.copy()
        del incomplete["cell_5_voltage"]

        res = engine.predict("EL1", incomplete)
        assert res.status == "INSUFFICIENT_DATA"
        assert res.is_anomaly is False
        assert res.predicted_fault == "unknown"
        assert "Incomplete telemetry" in res.trip_reasons[0]

    def test_nan_sensor_values_insufficient_data(self, nominal_raw):
        engine = RealTimeInferenceEngine()
        nan_data = nominal_raw.copy()
        nan_data["stack_current"] = float("nan")

        res = engine.predict("EL1", nan_data)
        assert res.status == "INSUFFICIENT_DATA"
        assert res.is_anomaly is False

    def test_membrane_pinhole_fault_detection(self, nominal_raw):
        engine = RealTimeInferenceEngine(anomaly_threshold=0.65)
        faulty = nominal_raw.copy()
        faulty["cell_1_voltage"] = 2.35  # Over-voltage spike on cell 1

        res = engine.predict("EL1", faulty)
        assert res.is_anomaly is True
        assert res.status == "ANOMALY_DETECTED"
        assert res.predicted_fault == "membrane_pinhole"
        assert res.alarm_tripped is True
        assert any("over-voltage" in r for r in res.trip_reasons)

    def test_gas_crossover_fault_detection(self, nominal_raw):
        engine = RealTimeInferenceEngine(anomaly_threshold=0.65)
        faulty = nominal_raw.copy()
        faulty["h2_flow_rate"] = 0.60  # Ratio 0.60 / 0.20 = 3.0 (abnormal > 2.0)

        res = engine.predict("EL1", faulty)
        assert res.is_anomaly is True
        assert res.status == "ANOMALY_DETECTED"
        assert res.predicted_fault == "gas_crossover"

    def test_pump_failure_low_water_flow_trip(self, nominal_raw):
        engine = RealTimeInferenceEngine(anomaly_threshold=0.65)
        faulty = nominal_raw.copy()
        faulty["water_flow"] = 0.05
        faulty["stack_current"] = 1.8

        res = engine.predict("EL1", faulty)
        assert res.is_anomaly is True
        assert res.alarm_tripped is True
        assert res.predicted_fault == "pump_failure"
        assert any("Low water flow" in r for r in res.trip_reasons)

    def test_over_pressure_safety_trip(self, nominal_raw):
        engine = RealTimeInferenceEngine(anomaly_threshold=0.65)
        faulty = nominal_raw.copy()
        faulty["tank_pressure"] = 36.0

        res = engine.predict("EL1", faulty)
        assert res.is_anomaly is True
        assert res.alarm_tripped is True
        assert res.predicted_fault == "over_pressure"
        assert any("Tank over-pressure" in r for r in res.trip_reasons)

    def test_cell_dryout_multi_cell_overvoltage(self, nominal_raw):
        engine = RealTimeInferenceEngine(anomaly_threshold=0.65)
        faulty = nominal_raw.copy()
        for i in range(1, 6):
            faulty[f"cell_{i}_voltage"] = 2.25

        res = engine.predict("EL1", faulty)
        assert res.is_anomaly is True
        assert res.predicted_fault == "cell_dryout"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. TelemetryConsumer Snapshot Aggregation to Inference Pipeline
# ═══════════════════════════════════════════════════════════════════════════════

class TestConsumerToInferenceIntegration:
    """Verifies that TelemetryConsumer aggregated state directly feeds RealTimeInferenceEngine."""

    def test_consumer_snapshot_to_inference_pipeline(self):
        consumer = TelemetryConsumer(use_tls=False)
        engine = RealTimeInferenceEngine()

        # Ingest all 12 stack sensors for EL1
        sensor_values = {
            "cell_1_voltage": 1.95,
            "cell_2_voltage": 1.95,
            "cell_3_voltage": 1.95,
            "cell_4_voltage": 1.95,
            "cell_5_voltage": 1.95,
            "stack_current": 1.8,
            "stack_temperature": 45.0,
            "stack_pressure": 1.2,
            "h2_flow_rate": 0.40,
            "o2_flow_rate": 0.20,
            "tank_pressure": 15.0,
            "water_flow": 1.0,
        }

        seq = 1
        for sensor_id, val in sensor_values.items():
            cell = int(sensor_id.split("_")[1]) if sensor_id.startswith("cell_") else None
            unit = "V" if "voltage" in sensor_id else ("A" if "current" in sensor_id else "degC")
            msg = json.dumps({
                "ts": "2026-10-20T02:00:00.000Z",
                "site_id": "plant-A",
                "stack_id": "EL1",
                "sensor_id": sensor_id,
                "cell": cell,
                "metrics": {"value": val, "unit": unit},
                "quality": {"qos": 1, "status": "OK", "seq": seq},
            })
            consumer.process_raw_message(f"electrolyser/plant-A/EL1/{sensor_id}", msg)
            seq += 1

        # Irradiance shared sensors
        for irr_idx, irr_val in [(1, 750.0), (2, 750.0)]:
            msg = json.dumps({
                "ts": "2026-10-20T02:00:00.000Z",
                "site_id": "plant-A",
                "stack_id": "PLANT",
                "sensor_id": f"irradiance_{irr_idx}",
                "metrics": {"value": irr_val, "unit": "W/m2"},
                "quality": {"qos": 1, "status": "OK", "seq": seq},
            })
            consumer.process_raw_message(f"electrolyser/plant-A/irradiance/{irr_idx}", msg)
            seq += 1

        snapshot = consumer.get_snapshot("EL1")
        assert snapshot is not None
        assert len(snapshot) == 14  # 12 stack + 2 plant irradiance

        result = engine.predict("EL1", snapshot)
        assert result.status == "HEALTHY"
        assert result.is_anomaly is False
        assert len(result.features_23) == 23


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Telegraf & Time-Series Ingestion Field Mapping Verification
# ═══════════════════════════════════════════════════════════════════════════════

class TestTelegrafFieldMapping:
    """Verifies telegraf configuration maps tag keys, json time key, and measurement names."""

    def test_telegraf_configuration_tags_and_fields(self):
        conf_file = ROOT / "telegraf" / "telegraf.conf"
        assert conf_file.exists()
        conf_str = conf_file.read_text()

        # Check MQTT input settings
        assert 'name_override = "electrolyser_sensor"' in conf_str
        assert 'data_format = "json"' in conf_str
        assert 'json_time_key' in conf_str
        assert 'tag_keys = ["el", "sensor", "unit", "site_id", "stack_id", "sensor_id"]' in conf_str

        # Check InfluxDB output bucket and org variables
        assert 'bucket       = "${INFLUX_BUCKET}"' in conf_str or 'bucket = "${INFLUX_BUCKET}"' in conf_str
        assert 'organization = "${INFLUX_ORG}"' in conf_str or 'organization = "${INFLUX_ORG}"' in conf_str

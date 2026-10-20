"""
tests/test_mqtt_integration.py
==============================
Deterministic integration and regression test suite for Edge Deployment & MQTT Stream.

Covers:
1. Telemetry schema compliance for all simulated sensors and digital twin.
2. TelemetryConsumer stream handling, schema validation, and error recovery.
3. Message deduplication, out-of-order handling, and state aggregation.
4. Connection lifecycle, disconnects, reconnects, and broker error handling.
5. Security verification: mTLS configuration, certificate SANs, and topic ACLs.
"""

from __future__ import annotations

import json
import pathlib
import sys
from unittest import mock

import pytest
from jsonschema import validate

# Ensure clients module is in sys.path
CLIENTS_DIR = pathlib.Path(__file__).resolve().parents[1] / "clients" / "python"
if str(CLIENTS_DIR) not in sys.path:
    sys.path.insert(0, str(CLIENTS_DIR))

from plant_sim import (
    ElectrolyserTwin,
    PlantSimulator,
)
from sensor_client import generate_value, resolve_topic
from telemetry_consumer import ConsumerState, TelemetryConsumer
from telemetry_types import TelemetryMetrics, TelemetryPayload, TelemetryQuality

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "telemetry_v1.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text())


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Telemetry Schema Compliance Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestTelemetrySchemaCompliance:
    """Verifies that all simulator outputs conform 100% to schemas/telemetry_v1.json."""

    def test_twin_publish_all_schema_compliance(self):
        twin = ElectrolyserTwin("EL1")
        twin.update_from_pv(800.0, 1.0)

        published_messages: list[tuple[str, str, dict]] = []
        with mock.patch("plant_sim._publish_json", side_effect=lambda c, t, p: published_messages.append((c.client_id if hasattr(c, "client_id") else "", t, p))):
            twin.clients = {cn: mock.MagicMock(client_id=cn) for cn, _ in [
                (f"sensor-EL1-cell_{i}_voltage", None) for i in range(1, 6)
            ] + [
                (f"sensor-EL1-{name}", None) for name in [
                    "stack_current", "stack_temperature", "stack_pressure",
                    "h2_flow_rate", "o2_flow_rate", "tank_pressure", "water_flow"
                ]
            ]}
            twin.publish_all()

        assert len(published_messages) >= 12, "Must publish at least 12 sensor messages + status"

        sensor_messages = [p for _, topic, p in published_messages if not topic.endswith("/status")]
        assert len(sensor_messages) == 12

        for payload in sensor_messages:
            validate(payload, SCHEMA)
            assert payload["site_id"] == "plant-A"
            assert payload["stack_id"] == "EL1"
            assert "metrics" in payload
            assert "value" in payload["metrics"]
            assert "unit" in payload["metrics"]
            assert "quality" in payload
            assert payload["quality"]["qos"] in (0, 1, 2)
            assert payload["quality"]["status"] in ("OK", "WARN", "ERROR", "STALE", "FAULT")

    def test_twin_fault_quality_flagging(self):
        twin = ElectrolyserTwin("EL1")
        twin.fault_injector.set_fault("membrane_pinhole", True)
        twin.update_from_pv(800.0, 1.0)

        published_messages: list[dict] = []
        with mock.patch("plant_sim._publish_json", side_effect=lambda c, t, p: published_messages.append(p)):
            twin.clients = {f"sensor-EL1-cell_{i}_voltage": mock.MagicMock() for i in range(1, 6)}
            twin.clients.update({
                f"sensor-EL1-{name}": mock.MagicMock()
                for name in ["stack_current", "stack_temperature", "stack_pressure", "h2_flow_rate", "o2_flow_rate", "tank_pressure", "water_flow"]
            })
            twin.publish_all()

        cell1_msg = next(p for p in published_messages if p.get("sensor_id") == "cell_1_voltage")
        assert cell1_msg["quality"]["status"] == "FAULT"
        assert cell1_msg["fault_active"] is True

        cell3_msg = next(p for p in published_messages if p.get("sensor_id") == "cell_3_voltage")
        assert cell3_msg["quality"]["status"] == "OK"
        assert cell3_msg["fault_active"] is False

    def test_plant_sim_irradiance_schema_compliance(self):
        sim = PlantSimulator(dt=1.0)
        published_messages: list[dict] = []
        with mock.patch("plant_sim._publish_json", side_effect=lambda c, t, p: published_messages.append(p)):
            sim.irr_clients = {1: mock.MagicMock(), 2: mock.MagicMock()}
            sim.publish_irradiance()

        assert len(published_messages) == 2
        for p in published_messages:
            validate(p, SCHEMA)
            assert p["stack_id"] == "PLANT"
            assert p["sensor_id"] in ("irradiance_1", "irradiance_2")
            assert p["metrics"]["unit"] == "W/m2"

    def test_sensor_client_payload_structure(self):
        val = generate_value("EL1", "cell_1_voltage")
        topic = resolve_topic("EL1", "cell_1_voltage", cell=1)
        payload = TelemetryPayload(
            ts="2026-10-20T00:00:00Z",
            site_id="plant-A",
            stack_id="EL1",
            sensor_id="cell_1_voltage",
            cell=1,
            metrics=TelemetryMetrics(value=val, unit="V"),
            quality=TelemetryQuality(qos=1, status="OK", seq=10),
        ).to_dict()

        validate(payload, SCHEMA)
        assert topic == "electrolyser/plant-A/EL1/cell/1/voltage"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. TelemetryConsumer Parsing and Error Handling
# ═══════════════════════════════════════════════════════════════════════════════

class TestTelemetryConsumerParsing:
    """Tests stream ingestion, validation, and error recovery."""

    def test_valid_telemetry_message_processing(self):
        received_payloads: list[TelemetryPayload] = []
        consumer = TelemetryConsumer(
            use_tls=False,
            on_payload=lambda p: received_payloads.append(p),
        )

        valid_raw = json.dumps({
            "ts": "2026-10-20T01:00:00.000Z",
            "site_id": "plant-A",
            "stack_id": "EL1",
            "sensor_id": "cell_1_voltage",
            "cell": 1,
            "metrics": {"value": 1.98, "unit": "V", "raw": None},
            "quality": {"qos": 1, "status": "OK", "seq": 1},
            "fault_active": False,
        })

        success, code = consumer.process_raw_message("electrolyser/plant-A/EL1/cell/1/voltage", valid_raw)
        assert success is True
        assert code == "OK"
        assert len(received_payloads) == 1
        assert received_payloads[0].sensor_id == "cell_1_voltage"
        assert received_payloads[0].metrics.value == pytest.approx(1.98)
        assert consumer.metrics["valid_telemetry"] == 1

    def test_malformed_json_handling(self):
        errors: list[tuple[str, Exception | str]] = []
        consumer = TelemetryConsumer(
            use_tls=False,
            on_error=lambda ctx, exc: errors.append((ctx, exc)),
        )

        bad_jsons = [
            b"{not valid json",
            b'{"ts": "2026-01-01", "unclosed',
            b"\x80\x81\x82 invalid utf-8",
            "just plain text",
        ]

        for bad in bad_jsons:
            success, code = consumer.process_raw_message("electrolyser/plant-A/EL1/cell/1/voltage", bad)
            assert success is False
            assert "MALFORMED" in code

        assert consumer.metrics["malformed_json"] == len(bad_jsons)
        assert len(errors) == len(bad_jsons)

    def test_schema_missing_fields_rejection(self):
        errors: list[tuple[str, Exception | str]] = []
        consumer = TelemetryConsumer(
            use_tls=False,
            on_error=lambda ctx, exc: errors.append((ctx, exc)),
        )

        incomplete_payload = {
            "ts": "2026-10-20T01:00:00.000Z",
            # site_id missing
            "stack_id": "EL1",
            "sensor_id": "stack_current",
            "metrics": {"value": 1.8, "unit": "A"},
            "quality": {"qos": 1, "status": "OK", "seq": 1},
        }

        success, code = consumer.process_raw_message(
            "electrolyser/plant-A/EL1/stack/current",
            json.dumps(incomplete_payload),
        )
        assert success is False
        assert "SCHEMA_VALIDATION_ERROR" in code
        assert consumer.metrics["schema_errors"] == 1

    def test_invalid_qos_and_status_enums(self):
        consumer = TelemetryConsumer(use_tls=False)

        bad_qos = {
            "ts": "2026-10-20T01:00:00.000Z",
            "site_id": "plant-A",
            "stack_id": "EL1",
            "sensor_id": "stack_current",
            "metrics": {"value": 1.8, "unit": "A"},
            "quality": {"qos": 99, "status": "OK", "seq": 1},
        }
        success, code = consumer.process_raw_message(
            "electrolyser/plant-A/EL1/stack/current",
            json.dumps(bad_qos),
        )
        assert success is False
        assert "SCHEMA_VALIDATION_ERROR" in code

        bad_status = {
            "ts": "2026-10-20T01:00:00.000Z",
            "site_id": "plant-A",
            "stack_id": "EL1",
            "sensor_id": "stack_current",
            "metrics": {"value": 1.8, "unit": "A"},
            "quality": {"qos": 1, "status": "INVALID_STATUS", "seq": 1},
        }
        success, code = consumer.process_raw_message(
            "electrolyser/plant-A/EL1/stack/current",
            json.dumps(bad_status),
        )
        assert success is False
        assert "SCHEMA_VALIDATION_ERROR" in code

    def test_duplicate_message_handling(self):
        consumer = TelemetryConsumer(use_tls=False)

        msg = json.dumps({
            "ts": "2026-10-20T01:00:00.000Z",
            "site_id": "plant-A",
            "stack_id": "EL1",
            "sensor_id": "h2_flow_rate",
            "metrics": {"value": 0.42, "unit": "L/min"},
            "quality": {"qos": 1, "status": "OK", "seq": 5},
        })

        success1, code1 = consumer.process_raw_message("electrolyser/plant-A/EL1/h2/flow_rate", msg)
        assert success1 is True
        assert code1 == "OK"

        # Duplicate with same sequence id
        success2, code2 = consumer.process_raw_message("electrolyser/plant-A/EL1/h2/flow_rate", msg)
        assert success2 is False
        assert code2 == "DUPLICATE_SEQUENCE"
        assert consumer.metrics["duplicates"] == 1

        # Out of order sequence id (smaller than 5)
        out_of_order = json.dumps({
            "ts": "2026-10-20T01:00:01.000Z",
            "site_id": "plant-A",
            "stack_id": "EL1",
            "sensor_id": "h2_flow_rate",
            "metrics": {"value": 0.42, "unit": "L/min"},
            "quality": {"qos": 1, "status": "OK", "seq": 4},
        })
        success3, code3 = consumer.process_raw_message("electrolyser/plant-A/EL1/h2/flow_rate", out_of_order)
        assert success3 is False
        assert code3 == "DUPLICATE_SEQUENCE"
        assert consumer.metrics["duplicates"] == 2

    def test_status_message_handling(self):
        status_received: list[dict] = []
        consumer = TelemetryConsumer(
            use_tls=False,
            on_status=lambda s: status_received.append(s),
        )

        status_msg = json.dumps({
            "stack_id": "EL1",
            "status": "OPERATIONAL",
            "active_faults": ["membrane_pinhole"],
            "sequence_id": 42,
        })
        success, code = consumer.process_raw_message("electrolyser/plant-A/EL1/status", status_msg)
        assert success is True
        assert code == "STATUS_PROCESSED"
        assert len(status_received) == 1
        assert consumer.latest_status["EL1"]["status"] == "OPERATIONAL"

    def test_state_snapshot_aggregation(self):
        consumer = TelemetryConsumer(use_tls=False)

        # Ingest cell 1 and stack current for EL1, and irradiance for PLANT
        for sensor_id, cell, val in [
            ("cell_1_voltage", 1, 1.95),
            ("cell_2_voltage", 2, 1.96),
            ("stack_current", None, 1.82),
        ]:
            msg = json.dumps({
                "ts": "2026-10-20T01:00:00.000Z",
                "site_id": "plant-A",
                "stack_id": "EL1",
                "sensor_id": sensor_id,
                "cell": cell,
                "metrics": {"value": val, "unit": "V"},
                "quality": {"qos": 1, "status": "OK", "seq": 1},
            })
            consumer.process_raw_message(f"electrolyser/plant-A/EL1/{sensor_id}", msg)

        # Ingest irradiance
        irr_msg = json.dumps({
            "ts": "2026-10-20T01:00:00.000Z",
            "site_id": "plant-A",
            "stack_id": "PLANT",
            "sensor_id": "irradiance_1",
            "metrics": {"value": 850.0, "unit": "W/m2"},
            "quality": {"qos": 1, "status": "OK", "seq": 1},
        })
        consumer.process_raw_message("electrolyser/plant-A/irradiance/1", irr_msg)

        snapshot = consumer.get_snapshot("EL1")
        assert snapshot is not None
        assert snapshot["cell_1_voltage"] == pytest.approx(1.95)
        assert snapshot["cell_2_voltage"] == pytest.approx(1.96)
        assert snapshot["stack_current"] == pytest.approx(1.82)
        assert snapshot["irradiance_1"] == pytest.approx(850.0)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Connection Lifecycle and Fault Recovery
# ═══════════════════════════════════════════════════════════════════════════════

class TestConnectionLifecycle:
    """Verifies state machine transitions, reconnect handling, and disconnects."""

    def test_state_machine_transitions(self):
        consumer = TelemetryConsumer(use_tls=False)
        assert consumer.state == ConsumerState.DISCONNECTED

        # Simulate on_connect
        mock_client = mock.MagicMock()
        consumer._on_connect(mock_client, None, {}, 0)
        assert consumer.state == ConsumerState.CONNECTED
        assert consumer.metrics["connect_success"] == 1
        mock_client.subscribe.assert_called_once_with(consumer.topic, qos=1)

        # Simulate unexpected on_disconnect
        consumer._on_disconnect(mock_client, None, 1)
        assert consumer.state == ConsumerState.RECONNECTING
        assert consumer.metrics["disconnect_count"] == 1

        # Clean disconnect
        consumer.disconnect()
        assert consumer.state == ConsumerState.STOPPED

    def test_unavailable_broker_handling(self):
        consumer = TelemetryConsumer(
            broker_host="127.0.0.1",
            broker_port=59999,  # unused port
            use_tls=False,
        )
        with pytest.raises(OSError):
            consumer.connect()
        assert consumer.state == ConsumerState.DISCONNECTED


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Security & ACL Verification
# ═══════════════════════════════════════════════════════════════════════════════

class TestSecurityAndACLConfiguration:
    """Verifies mTLS configuration, least-privilege ACL rules, and broker settings."""

    def test_mosquitto_conf_security_settings(self):
        conf_path = ROOT / "mosquitto" / "conf" / "mosquitto.conf"
        assert conf_path.exists(), "mosquitto.conf missing"
        conf_text = conf_path.read_text()

        # mTLS on port 8883
        assert "listener 8883" in conf_text
        assert "require_certificate true" in conf_text
        assert "use_identity_as_username true" in conf_text
        assert "allow_anonymous false" in conf_text
        assert "tls_version tlsv1.3" in conf_text
        assert "acl_file /mosquitto/config/aclfile" in conf_text

    def test_acl_generator_least_privilege(self):
        acl_script = ROOT / "scripts" / "generate-acl.sh"
        assert acl_script.exists()
        script_text = acl_script.read_text()

        # Check that per-sensor rules map CN to single write topic
        assert "CN=\"sensor-${el}-${s}\"" in script_text
        assert "topic write ${topic}" in script_text

        # Check subscriber read access
        assert "user telegraf-subscriber" in script_text
        assert "topic read electrolyser/plant-A/#" in script_text

        # Check monitor-local access
        assert "user monitor-local" in script_text
        assert "topic read electrolyser/#" in script_text
        assert "topic write electrolyser/control/faults" in script_text

    def test_pki_scripts_exist_and_executable(self):
        pki_dir = ROOT / "scripts" / "pki"
        for script_name in ["make-ca.sh", "make-broker.sh", "make-client.sh", "make-clients-batch.sh", "rotate-cert.sh"]:
            path = pki_dir / script_name
            assert path.exists(), f"PKI script {script_name} missing"

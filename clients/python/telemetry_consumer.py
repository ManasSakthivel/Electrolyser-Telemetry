"""
telemetry_consumer.py
=====================
Edge MQTT telemetry stream consumer, schema validator, and pipeline ingestion handler.

Features:
- Subscribes to plant telemetry topics (e.g. ``electrolyser/plant-A/#``).
- Strict schema validation against ``schemas/telemetry_v1.json`` and ``TelemetryPayload``.
- Robust error handling for malformed JSON, schema violations, and corrupt payloads.
- Message deduplication tracking monotonic sequence numbers and timestamps.
- Connection state machine with reconnect handling.
- Multi-sensor state aggregation providing synchronized snapshots for ML models.
"""

from __future__ import annotations

import json
import logging
import pathlib
import ssl
import threading
from collections.abc import Callable

try:
    from jsonschema import ValidationError, validate
except ImportError:
    ValidationError = Exception  # type: ignore[misc,assignment]
    validate = None

from paho.mqtt import client as mqtt
from telemetry_types import TelemetryPayload

log = logging.getLogger("telemetry_consumer")
ROOT = pathlib.Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schemas" / "telemetry_v1.json"


class ConsumerState:
    DISCONNECTED = "DISCONNECTED"
    CONNECTING   = "CONNECTING"
    CONNECTED    = "CONNECTED"
    RECONNECTING = "RECONNECTING"
    STOPPED      = "STOPPED"


class TelemetryConsumer:
    """
    Production-grade edge MQTT consumer with schema validation and fault tolerance.
    """

    def __init__(
        self,
        broker_host: str = "127.0.0.1",
        broker_port: int = 8883,
        client_id: str = "telemetry-consumer",
        ca_cert: pathlib.Path | str | None = None,
        client_cert: pathlib.Path | str | None = None,
        client_key: pathlib.Path | str | None = None,
        use_tls: bool = True,
        topic: str = "electrolyser/plant-A/#",
        on_payload: Callable[[TelemetryPayload], None] | None = None,
        on_status: Callable[[dict], None] | None = None,
        on_error: Callable[[str, Exception | str], None] | None = None,
    ) -> None:
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.client_id = client_id
        self.use_tls = use_tls
        self.topic = topic

        self.ca_cert = pathlib.Path(ca_cert) if ca_cert else ROOT / "certs/ca/ca.crt"
        self.client_cert = pathlib.Path(client_cert) if client_cert else ROOT / "certs/clients/telegraf-subscriber/client.crt"
        self.client_key = pathlib.Path(client_key) if client_key else ROOT / "certs/clients/telegraf-subscriber/client.key"

        self.on_payload = on_payload
        self.on_status = on_status
        self.on_error = on_error

        self.state = ConsumerState.DISCONNECTED
        self._lock = threading.Lock()
        self._client: mqtt.Client | None = None

        # Load JSON schema
        if SCHEMA_PATH.exists():
            self._schema: dict | None = json.loads(SCHEMA_PATH.read_text())
        else:
            self._schema = None

        # Rolling state storage per stack: stack_id -> {sensor_id: TelemetryPayload}
        self.latest_sensor_data: dict[str, dict[str, TelemetryPayload]] = {}
        # Latest sequence tracker for deduplication: (stack_id, sensor_id) -> last_seq
        self._seq_tracker: dict[tuple[str, str], int] = {}
        # Latest plant status per stack
        self.latest_status: dict[str, dict] = {}

        # Observability metrics
        self.metrics = {
            "received": 0,
            "valid_telemetry": 0,
            "status_messages": 0,
            "malformed_json": 0,
            "schema_errors": 0,
            "duplicates": 0,
            "connect_success": 0,
            "disconnect_count": 0,
        }

    # ── Client initialization ──────────────────────────────────────────────────
    def _create_mqtt_client(self) -> mqtt.Client:
        if hasattr(mqtt, "CallbackAPIVersion"):
            client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2,
                client_id=self.client_id,
                protocol=mqtt.MQTTv5,
            )
        else:
            client = mqtt.Client(client_id=self.client_id, protocol=mqtt.MQTTv5)

        if self.use_tls and self.ca_cert.exists() and self.client_cert.exists() and self.client_key.exists():
            client.tls_set(
                ca_certs=str(self.ca_cert),
                certfile=str(self.client_cert),
                keyfile=str(self.client_key),
                tls_version=ssl.PROTOCOL_TLS_CLIENT,
            )
            client.tls_insecure_set(False)

        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        return client

    def connect(self) -> None:
        """Connect to the broker and start background network loop."""
        with self._lock:
            self.state = ConsumerState.CONNECTING
            self._client = self._create_mqtt_client()
            try:
                self._client.connect(self.broker_host, self.broker_port, keepalive=30)
                self._client.loop_start()
            except Exception as exc:
                self.state = ConsumerState.DISCONNECTED
                log.error("Failed to connect to broker %s:%d — %s", self.broker_host, self.broker_port, exc)
                if self.on_error:
                    self.on_error("connect", exc)
                raise

    def disconnect(self) -> None:
        """Stop background network loop and disconnect cleanly."""
        with self._lock:
            self.state = ConsumerState.STOPPED
            if self._client:
                try:
                    self._client.loop_stop()
                    self._client.disconnect()
                except Exception as exc:
                    log.debug("Error during disconnect: %s", exc)
                finally:
                    self._client = None

    # ── MQTT Callbacks ─────────────────────────────────────────────────────────
    def _on_connect(self, client: mqtt.Client, userdata: object, flags: dict, reason_code: object, properties: object = None) -> None:
        rc = getattr(reason_code, "value", reason_code)
        if rc == 0:
            with self._lock:
                self.state = ConsumerState.CONNECTED
                self.metrics["connect_success"] += 1
            log.info("Consumer connected to MQTT broker (%s:%d)", self.broker_host, self.broker_port)
            client.subscribe(self.topic, qos=1)
        else:
            with self._lock:
                self.state = ConsumerState.DISCONNECTED
            log.warning("MQTT connection refused with code %s", rc)

    def _on_disconnect(self, client: mqtt.Client, userdata: object, *args: object, **kwargs: object) -> None:
        # Handles both VERSION1 (client, userdata, rc) and VERSION2 (client, userdata, flags, reason_code, properties)
        with self._lock:
            if self.state != ConsumerState.STOPPED:
                self.state = ConsumerState.RECONNECTING
            self.metrics["disconnect_count"] += 1
        log.warning("Disconnected from MQTT broker")

    def _on_message(self, client: mqtt.Client, userdata: object, msg: mqtt.MQTTMessage) -> None:
        self.process_raw_message(msg.topic, msg.payload)

    # ── Core Message Processing ────────────────────────────────────────────────
    def process_raw_message(self, topic: str, payload_bytes: bytes | str) -> tuple[bool, str]:
        """
        Parse, validate against schema, and process a raw message.
        Returns (success: bool, status_code: str).
        """
        with self._lock:
            self.metrics["received"] += 1

        # 1. Parse JSON
        if isinstance(payload_bytes, bytes):
            try:
                payload_str = payload_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                with self._lock:
                    self.metrics["malformed_json"] += 1
                if self.on_error:
                    self.on_error("unicode_decode", exc)
                return False, "MALFORMED_UTF8"
        else:
            payload_str = payload_bytes

        try:
            data = json.loads(payload_str)
        except json.JSONDecodeError as exc:
            with self._lock:
                self.metrics["malformed_json"] += 1
            log.warning("Malformed JSON received on %s: %s", topic, exc)
            if self.on_error:
                self.on_error("json_decode", exc)
            return False, "MALFORMED_JSON"

        if not isinstance(data, dict):
            with self._lock:
                self.metrics["malformed_json"] += 1
            return False, "NON_DICT_PAYLOAD"

        # 2. Handle status / control messages
        if topic.endswith("/status"):
            stack_id = data.get("stack_id") or data.get("el")
            if stack_id:
                with self._lock:
                    self.latest_status[stack_id] = data
                    self.metrics["status_messages"] += 1
                if self.on_status:
                    try:
                        self.on_status(data)
                    except Exception:
                        log.exception("Error in on_status callback")
                return True, "STATUS_PROCESSED"

        # 3. Schema validation against schemas/telemetry_v1.json
        if self._schema is not None and validate is not None:
            try:
                validate(data, self._schema)
            except ValidationError as exc:
                with self._lock:
                    self.metrics["schema_errors"] += 1
                log.warning("Schema validation error on %s: %s", topic, getattr(exc, "message", str(exc)))
                if self.on_error:
                    self.on_error("schema_validation", exc)
                return False, f"SCHEMA_VALIDATION_ERROR: {getattr(exc, 'message', str(exc))}"

        # 4. Construct typed TelemetryPayload
        try:
            telemetry = TelemetryPayload.from_dict(data)
        except (KeyError, ValueError, TypeError) as exc:
            with self._lock:
                self.metrics["schema_errors"] += 1
            log.warning("TelemetryPayload deserialisation error on %s: %s", topic, exc)
            if self.on_error:
                self.on_error("dataclass_deserialisation", exc)
            return False, f"PAYLOAD_TYPE_ERROR: {exc}"

        # 5. Check for duplicate sequence numbers
        key = (telemetry.stack_id, telemetry.sensor_id)
        with self._lock:
            last_seq = self._seq_tracker.get(key)
            if last_seq is not None and telemetry.quality.seq <= last_seq:
                self.metrics["duplicates"] += 1
                log.debug("Duplicate or out-of-order sequence %d <= %d for %s", telemetry.quality.seq, last_seq, key)
                return False, "DUPLICATE_SEQUENCE"

            self._seq_tracker[key] = telemetry.quality.seq
            self.latest_sensor_data.setdefault(telemetry.stack_id, {})[telemetry.sensor_id] = telemetry
            self.metrics["valid_telemetry"] += 1

        # 6. Dispatch to callback
        if self.on_payload:
            try:
                self.on_payload(telemetry)
            except Exception:
                log.exception("Error in on_payload callback")

        return True, "OK"

    # ── State Aggregation for ML Feature Vector ────────────────────────────────
    def get_snapshot(self, stack_id: str) -> dict[str, float] | None:
        """
        Return the latest sensor reading snapshot for a stack as a flat dictionary,
        including shared irradiance readings.
        """
        with self._lock:
            stack_data = self.latest_sensor_data.get(stack_id, {})
            plant_data = self.latest_sensor_data.get("PLANT", {})

            if not stack_data:
                return None

            snapshot: dict[str, float] = {}
            for sensor_id, tel in stack_data.items():
                snapshot[sensor_id] = tel.metrics.value

            for sensor_id, tel in plant_data.items():
                snapshot[sensor_id] = tel.metrics.value

            return snapshot

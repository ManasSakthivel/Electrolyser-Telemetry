"""
telemetry_types.py
==================
Typed dataclasses for all telemetry payload variants in the electrolyser
telemetry system.  These types serve three purposes:

1.  **Documentation** — self-describing payload structure.
2.  **Validation** — ``from_dict()`` raises ``TypeError`` on missing or
    wrongly-typed fields, catching schema drift early.
3.  **ML pipeline** — ``to_feature_row()`` returns a flat dict compatible
    with ``pandas.DataFrame.from_records()``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class TelemetryQuality:
    """Data quality metadata attached to every sensor message."""
    qos:    int             # MQTT QoS level (0, 1, or 2)
    status: str             # OK | WARN | ERROR | STALE | FAULT
    seq:    int             # monotonically increasing per-sensor counter

    def __post_init__(self):
        if self.qos not in (0, 1, 2):
            raise ValueError(f"qos must be 0, 1, or 2; got {self.qos}")
        if self.status not in ("OK", "WARN", "ERROR", "STALE", "FAULT"):
            raise ValueError(f"Unknown status: {self.status}")


@dataclass(frozen=True)
class TelemetryMetrics:
    """Measured value and engineering unit."""
    value: float
    unit:  str
    raw:   float | None = None  # optional pre-calibration raw reading


@dataclass
class TelemetryPayload:
    """
    Canonical telemetry payload.

    Matches ``schemas/telemetry_v1.json`` exactly.  Use ``from_dict()`` to
    deserialise an incoming MQTT JSON message.
    """
    ts:        str              # ISO-8601 UTC (e.g. "2025-01-01T00:00:00.000Z")
    site_id:   str              # e.g. "rvce-plant-A"
    stack_id:  str              # e.g. "EL1", "EL2"
    sensor_id: str              # e.g. "cell_1_voltage"
    metrics:   TelemetryMetrics
    quality:   TelemetryQuality
    cell:      int | None    = None   # 1-5 for per-cell sensors, else None
    fault_active: bool | None = None

    @classmethod
    def from_dict(cls, d: dict) -> TelemetryPayload:
        """Deserialise from a raw JSON-parsed dict.  Raises ``KeyError`` on missing fields."""
        return cls(
            ts        = d["ts"],
            site_id   = d["site_id"],
            stack_id  = d["stack_id"],
            sensor_id = d["sensor_id"],
            metrics   = TelemetryMetrics(
                value = float(d["metrics"]["value"]),
                unit  = d["metrics"]["unit"],
                raw   = d["metrics"].get("raw"),
            ),
            quality   = TelemetryQuality(
                qos    = int(d["quality"]["qos"]),
                status = d["quality"]["status"],
                seq    = int(d["quality"]["seq"]),
            ),
            cell         = d.get("cell"),
            fault_active = d.get("fault_active"),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    def to_feature_row(self) -> dict:
        """Flat dict suitable for pandas.DataFrame.from_records()."""
        return {
            "ts":           self.ts,
            "site_id":      self.site_id,
            "stack_id":     self.stack_id,
            "sensor_id":    self.sensor_id,
            "cell":         self.cell,
            "value":        self.metrics.value,
            "unit":         self.metrics.unit,
            "qos":          self.quality.qos,
            "status":       self.quality.status,
            "seq":          self.quality.seq,
            "fault_active": self.fault_active,
        }

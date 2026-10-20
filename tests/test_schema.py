import datetime
import json
import pathlib

from jsonschema import validate

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas" / "telemetry_v1.json").read_text())

def test_minimal_valid():
    payload = {
        "ts": datetime.datetime.now(tz=datetime.UTC).isoformat(),
        "site_id": "rvce-plant-A",
        "stack_id": "stack-03",
        "sensor_id": "h2_purity",
        "metrics": {"value": 99.9, "unit": "%"},
        "quality": {"qos": 1, "status": "OK", "seq": 1}
    }
    validate(payload, SCHEMA)


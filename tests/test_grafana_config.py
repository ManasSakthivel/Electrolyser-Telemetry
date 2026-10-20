"""Static contract checks between Grafana provisioning, the dashboard and Telegraf output."""

from __future__ import annotations

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "grafana" / "dashboards" / "electrolyser_telemetry.json"
DATASOURCE = ROOT / "grafana" / "provisioning" / "datasources" / "influxdb.yml"


def _dicts(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _dicts(value)
    elif isinstance(node, list):
        for item in node:
            yield from _dicts(item)


def _dashboard():
    return json.loads(DASHBOARD.read_text())


def test_dashboard_datasource_uids_match_provisioned_datasource():
    provisioned = set(re.findall(r"^\s*uid:\s*(\S+)\s*$", DATASOURCE.read_text(), re.MULTILINE))
    referenced = {d["datasource"]["uid"] for d in _dicts(_dashboard()) if isinstance(d.get("datasource"), dict) and "uid" in d["datasource"]}
    assert referenced, "dashboard has no datasource references"
    assert referenced <= provisioned, f"dashboard references unprovisioned datasource uids: {referenced - provisioned}"


def test_dashboard_field_filters_match_telegraf_output_field():
    queries = [d["query"] for d in _dicts(_dashboard()) if isinstance(d.get("query"), str)]
    assert queries, "dashboard has no Flux queries"
    fields = set()
    for query in queries:
        fields |= set(re.findall(r'r\["_field"\] == "([^"]+)"', query))
    assert fields == {"value"}, f"dashboard filters on fields {fields}; Telegraf renames to 'value'"

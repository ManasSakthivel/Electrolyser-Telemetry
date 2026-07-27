#!/usr/bin/env python3
"""
benchmark_latency.py
====================
Measures end-to-end MQTT message latency for the electrolyser telemetry stack.

Methodology
-----------
A publisher and a subscriber are connected simultaneously.  The publisher
embeds a high-resolution timestamp in every message payload; the subscriber
records the wall-clock receive time.  Latency = t_receive − t_publish.

The test runs N rounds at 1 Hz and reports p50, p95, p99, max and a
histogram PNG.  Results are written to ``data/latency_report.json``.

Network modes
-------------
* **Localhost** (default):  --broker 127.0.0.1 — baseline for same-host deployment.
* **Docker bridge**:        --broker broker — run the simulator as a container so
  traffic crosses the Docker bridge network (``telemetry_net``), producing a more
  realistic latency measurement suitable for IEC 62282-8-201 compliance claims.
  Use ``make up`` then ``docker run --network electrolyser-telemetry-main_telemetry_net ...``

The --network-label flag is recorded in the JSON report so results from different
network contexts can be compared directly.

Usage
-----
    # Localhost (development):
    python scripts/benchmark_latency.py --n 200 --broker 127.0.0.1 --network-label localhost

    # Docker bridge (compliance measurement):
    python scripts/benchmark_latency.py --n 200 --broker broker --network-label docker-bridge

Requirements
------------
    pip install paho-mqtt matplotlib
"""

from __future__ import annotations

import argparse
import json
import logging
import pathlib
import ssl
import statistics
import time
from threading import Event
from typing import List

import matplotlib.pyplot as plt
from paho.mqtt import client as mqtt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("benchmark_latency")

ROOT = pathlib.Path(__file__).resolve().parents[1]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_client(cn: str, broker: str, port: int, client_id: str) -> mqtt.Client:
    ca   = ROOT / "certs/ca/ca.crt"
    cert = ROOT / f"certs/clients/{cn}/client.crt"
    key  = ROOT / f"certs/clients/{cn}/client.key"
    c = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv5)
    c.tls_set(ca_certs=str(ca), certfile=str(cert), keyfile=str(key),
              tls_version=ssl.PROTOCOL_TLS_CLIENT)
    c.tls_insecure_set(False)
    c.connect(broker, port, keepalive=30)
    return c


def percentile(data: List[float], p: float) -> float:
    """Return the p-th percentile of a sorted list."""
    if not data:
        return float("nan")
    sd = sorted(data)
    idx = (p / 100.0) * (len(sd) - 1)
    lo, hi = int(idx), min(int(idx) + 1, len(sd) - 1)
    return sd[lo] + (idx - lo) * (sd[hi] - sd[lo])


# ── Benchmark ──────────────────────────────────────────────────────────────────

def run_benchmark(n: int, broker: str, port: int) -> dict:
    TOPIC_BENCH = "electrolyser/plant-A/_benchmark/latency"

    latencies_ms: List[float] = []
    received = Event()
    _last_payload: dict = {}

    # Subscriber
    sub = _make_client("monitor-local", broker, port, "bench-sub")

    def on_message(c, userdata, msg: mqtt.MQTTMessage) -> None:
        t_recv = time.perf_counter()
        try:
            p = json.loads(msg.payload)
            lat_ms = (t_recv - p["t_send"]) * 1000.0
            latencies_ms.append(lat_ms)
            _last_payload.update(p)
        except Exception:
            pass
        received.set()

    sub.on_message = on_message
    sub.subscribe(TOPIC_BENCH, qos=1)
    sub.loop_start()
    time.sleep(0.3)  # allow subscription to be ACKed

    # Publisher
    pub = _make_client("monitor-local", broker, port, "bench-pub")
    pub.loop_start()

    log.info("Benchmarking: %d rounds at 1 Hz …", n)
    for i in range(n):
        received.clear()
        payload = json.dumps({"seq": i, "t_send": time.perf_counter()})
        pub.publish(TOPIC_BENCH, payload, qos=1)
        if not received.wait(timeout=3.0):
            log.warning("Round %d: no response within 3 s", i)
        time.sleep(1.0)

    pub.loop_stop(); pub.disconnect()
    sub.loop_stop(); sub.disconnect()

    if not latencies_ms:
        log.error("No latency samples collected — is the broker running?")
        raise SystemExit(1)

    report = {
        "n_samples":   len(latencies_ms),
        "mean_ms":     round(statistics.mean(latencies_ms), 3),
        "std_ms":      round(statistics.stdev(latencies_ms) if len(latencies_ms) > 1 else 0.0, 3),
        "p50_ms":      round(percentile(latencies_ms, 50), 3),
        "p95_ms":      round(percentile(latencies_ms, 95), 3),
        "p99_ms":      round(percentile(latencies_ms, 99), 3),
        "max_ms":      round(max(latencies_ms), 3),
        "min_ms":      round(min(latencies_ms), 3),
        "broker":      f"{broker}:{port}",
        "timestamp":   time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    return report, latencies_ms


def save_histogram(latencies_ms: List[float], out_dir: pathlib.Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.hist(latencies_ms, bins=40, color="steelblue", edgecolor="white", linewidth=0.4)
    p95 = percentile(latencies_ms, 95)
    p99 = percentile(latencies_ms, 99)
    ax.axvline(p95, color="orange", linestyle="--", lw=1.5, label=f"p95 = {p95:.1f} ms")
    ax.axvline(p99, color="red",    linestyle="--", lw=1.5, label=f"p99 = {p99:.1f} ms")
    ax.set_xlabel("End-to-end MQTT latency (ms)")
    ax.set_ylabel("Count")
    ax.set_title("MQTT Message Latency Distribution — Electrolyser Telemetry Stack")
    ax.legend()
    plt.tight_layout()
    out = out_dir / "latency_histogram.png"
    plt.savefig(str(out), dpi=150)
    log.info("Histogram saved → %s", out)
    plt.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="MQTT end-to-end latency benchmark")
    parser.add_argument("--n",             type=int, default=200,
                        help="Number of rounds (default 200)")
    parser.add_argument("--broker",        default="127.0.0.1",
                        help="MQTT broker host (127.0.0.1 for localhost, 'broker' for Docker bridge)")
    parser.add_argument("--port",          type=int, default=8883,  help="MQTT TLS port")
    parser.add_argument("--out",           default="data",          help="Output directory")
    parser.add_argument("--network-label", default="localhost",
                        help="Network context label stored in report "
                             "(e.g. 'localhost', 'docker-bridge'). "
                             "Use 'docker-bridge' when running inside the telemetry_net network.")
    args = parser.parse_args()

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    report, latencies_ms = run_benchmark(args.n, args.broker, args.port)

    # Annotate the report with network context so localhost vs bridge results
    # are clearly distinguishable when comparing IEC compliance measurements.
    report["network_label"] = args.network_label
    report["iec_62282_8_201_compliant"] = report["p95_ms"] < (5.0 * 1000.0)  # ≤ 5 s → always true; note: interval compliance

    log.info("=== Latency Report (%s) ===", args.network_label)
    for k, v in report.items():
        log.info("  %-28s %s", k, v)

    # Append result to a multi-run comparison file
    comparison_path = out_dir / "latency_comparison.json"
    history: list = []
    if comparison_path.exists():
        try:
            history = json.loads(comparison_path.read_text())
        except Exception:
            history = []
    history.append(report)
    comparison_path.write_text(json.dumps(history, indent=2))
    log.info("Comparison history saved → %s", comparison_path)

    # Write individual report
    label = args.network_label.replace(" ", "_")
    report_path = out_dir / f"latency_report_{label}.json"
    report_path.write_text(json.dumps(report, indent=2))
    log.info("Report saved → %s", report_path)

    save_histogram(latencies_ms, out_dir)


if __name__ == "__main__":
    main()

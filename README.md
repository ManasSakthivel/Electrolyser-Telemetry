# Electrolyser Telemetry System

![CI](https://github.com/your-org/electrolyser-telemetry/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.11%20|%203.12-blue)
![License](https://img.shields.io/badge/license-MIT-green)

A production-grade **secure IoT telemetry and digital-twin platform** for
monitoring green hydrogen electrolyser plants.  The system spans five
software layers — simulation, security, messaging, storage, and
visualisation — and includes an ML pipeline for fault detection from
labelled sensor data.

---

## Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│  LAYER 1 — SIMULATION  (clients/python/plant_sim.py)               │
│  Physics-based digital twin (EL1, EL2) + PV irradiance model       │
│  16 injectable fault modes  ·  1 Hz telemetry  ·  per-sensor certs │
└───────────────────────┬────────────────────────────────────────────┘
                        │ MQTT QoS-1, mTLS (X.509 per device)
                        ▼
┌────────────────────────────────────────────────────────────────────┐
│  LAYER 2 — SECURITY  (mosquitto/  +  scripts/pki/)                 │
│  Eclipse Mosquitto  ·  TLS 1.3  ·  per-sensor X.509 certificates  │
│  ACL-based topic authorisation  ·  automated cert rotation         │
└───────────────────────┬────────────────────────────────────────────┘
                        │ MQTT subscribe (mTLS)
                        ▼
┌────────────────────────────────────────────────────────────────────┐
│  LAYER 3 — INGESTION & STORAGE  (telegraf/  +  InfluxDB 2.7)       │
│  Telegraf parses JSON payloads  →  InfluxDB time-series bucket     │
│  Tag schema: el, sensor, cell, unit  ·  1 s interval               │
└───────────────────────┬────────────────────────────────────────────┘
                        │ Flux queries
                        ▼
┌────────────────────────────────────────────────────────────────────┐
│  LAYER 4 — VISUALISATION  (grafana/  +  web_simulation/)           │
│  Grafana dashboards  ·  React SCADA P&ID (WebSocket MQTT, port 9001)│
└────────────────────────────────────────────────────────────────────┘
                        │ Parquet export (scripts/export_dataset.py)
                        ▼
┌────────────────────────────────────────────────────────────────────┐
│  LAYER 5 — ML PIPELINE  (notebooks/anomaly_detection.ipynb)        │
│  Isolation Forest (unsupervised)  ·  Random Forest (supervised)    │
│  Derived features: H₂/O₂ ratio, cell voltage std, stack power      │
└────────────────────────────────────────────────────────────────────┘
```

---

## Key Software Components

| Component | Technology | Purpose |
|---|---|---|
| [`plant_sim.py`](clients/python/plant_sim.py) | Python 3.11, paho-mqtt | Physics-based digital twin; 16 fault modes; per-device mTLS |
| [`sensor_client.py`](clients/python/sensor_client.py) | Python 3.11 | Standalone single-sensor publisher (mTLS) |
| [`export_dataset.py`](scripts/export_dataset.py) | Python, pandas, pyarrow | Labelled telemetry → Parquet/CSV for ML training |
| [`anomaly_detection.ipynb`](notebooks/anomaly_detection.ipynb) | scikit-learn | Isolation Forest + Random Forest fault classifier |
| [`mosquitto.conf`](mosquitto/conf/mosquitto.conf) | Mosquitto 2.0 | TLS 1.3, cert auth, per-topic ACL, hardened broker |
| [`telegraf.conf`](telegraf/telegraf.conf) | Telegraf 1.31 | mTLS MQTT subscribe → InfluxDB v2 write |
| [`docker-compose.yml`](docker-compose.yml) | Docker Compose | Full stack: broker + influx + telegraf + grafana |
| [`web_simulation/`](web_simulation/) | React 19, Vite, TailwindCSS | Real-time SCADA P&ID dashboard (MQTT WebSocket) |
| [`tests/`](tests/) | pytest | 30+ unit tests; physics, faults, schema, topic resolution |
| [`.github/workflows/ci.yml`](.github/workflows/ci.yml) | GitHub Actions | Multi-version CI: lint (ruff) + test (pytest) |

---

## Security Architecture

```
                       ┌──────── Certificate Authority ────────┐
                       │  certs/ca/ca.crt  (self-signed root)  │
                       └───────────────────┬───────────────────┘
                ┌──────────────────────────┼────────────────────────┐
                ▼                          ▼                         ▼
     broker.crt (server)      sensor-EL1-cell_1_voltage.crt    telegraf-subscriber.crt
      (Mosquitto)                 (one per sensor)                (Telegraf)
```

Every sensor has a **unique X.509 certificate** signed by the plant CA.  The
broker enforces:

- **TLS 1.3** on all connections (port 8883 mTLS, port 9001 TLS WebSocket)
- **Certificate-based identity** — CN extracted as MQTT username
- **Per-sensor ACL** — each sensor can only publish to its own topic
- **Automated rotation** — `./scripts/pki/rotate-cert.sh [CN|all]`

---

## MQTT Topic Namespace

```
electrolyser/
└── plant-A/
    ├── EL1/
    │   ├── cell/{1-5}/voltage        (V)
    │   ├── stack/current             (A)
    │   ├── stack/temperature         (°C)
    │   ├── stack/pressure            (bar)
    │   ├── h2/flow_rate              (L/min)
    │   ├── o2/flow_rate              (L/min)
    │   ├── tank/pressure             (bar)
    │   ├── water_flow                (L/min)
    │   └── status                    (JSON: OPERATIONAL | TRIPPED)
    ├── EL2/ (same structure)
    └── irradiance/{1,2}              (W/m²)
    control/
    └── faults                        (JSON fault injection commands)
```

---

## Quick Start

### 1. Bootstrap PKI and secrets

```bash
# Copy and configure environment variables (NEVER commit .env)
cp .env.example .env
# Edit .env — set strong passwords and generate a token:
#   openssl rand -hex 32

# Create all certificates (CA → broker → 26 sensor clients)
make setup
```

### 2. Start the stack

```bash
make up
# Services:  Mosquitto :8883/:9001  |  InfluxDB :8086  |  Grafana :3000
```

### 3. Run the digital-twin simulator

```bash
make sim
# Publishes ~26 MQTT topics at 1 Hz using per-device mTLS certificates
```

### 4. Open the SCADA web dashboard

```bash
cd web_simulation && npm install && npm run dev
# Open http://localhost:5173
```

### 5. Inject a fault (separate terminal)

```bash
# Activate membrane pinhole on EL1
mosquitto_pub -h 127.0.0.1 -p 8883 \
  --cafile certs/ca/ca.crt \
  --cert certs/clients/monitor-local/client.crt \
  --key  certs/clients/monitor-local/client.key \
  -t "electrolyser/control/faults" \
  -m '{"el":"EL1","fault":"membrane_pinhole","active":true}'
```

### 6. Export a labelled dataset

```bash
make export
# Writes data/telemetry_labelled.parquet + .csv  (300 s collection window)
```

### 7. Run anomaly detection

```bash
cd notebooks && jupyter lab anomaly_detection.ipynb
```

---

## Running Tests

```bash
make test
# or directly:
pytest tests/ -v
```

Tests cover:

- Butler-Volmer activation overpotential formula correctness
- Monotonicity of stack voltage with current
- All 16 fault modes produce expected telemetry signatures (no live broker)
- JSON schema validation (valid, missing field, invalid enum)
- MQTT topic resolution for all sensor types
- Sensor value ranges for all sensor types

---

## Fault Simulation

The fault injection harness supports 16 modes, all triggerable via MQTT:

| Fault | Observable Signature |
|---|---|
| `membrane_pinhole` | Cell 1 voltage +500 mV, H₂ flow +20% |
| `gas_crossover` | H₂/O₂ ratio ≠ 2.0 (> 2.1 or < 1.9) |
| `cell_flooding` | Cells 3–4 drop to < 1.4 V |
| `cell_dryout` | All cells > 2.2 V, temperature rising |
| `pump_failure` | Water flow = 0 L/min |
| `dcdc_failure` | Stack current = 0, open-circuit voltage |
| `over_pressure` | Tank pressure spikes to 40 bar |
| `solar_transient` | Periodic current spike > 600 A |
| `loose_bolt` | Current 25% lower than expected |
| `o2_blockage` | O₂ flow drops to 20% of nominal |
| `voltage_sensor_drift` | Cell 5 stuck at 0.0 V |
| `temp_sensor_failure` | Temperature stuck at 0.0 °C |
| `irradiance_drift` | Irradiance sensor 1 diverges > 300 W/m² |
| `level_sensor` | Tank pressure noisy (±2 bar random) |
| `telemetry_dropout` | No MQTT messages published for EL |
| `none` | Clear all faults |

---

## ML Pipeline

```
data/telemetry_labelled.parquet
          │
          ▼
Feature engineering (notebooks/anomaly_detection.ipynb)
  · Raw: 14 sensor readings per tick
  · Derived: cell_voltage_std, h2/o2 ratio, stack_power, cell_voltage_min/max
          │
          ├─► Isolation Forest (unsupervised)
          │     Trained on normal data only — detects unknown/novel faults
          │
          └─► Random Forest Classifier (supervised, 16-class)
                5-fold CV accuracy reported; confusion matrix + feature importance
```

---

## Project Structure

```
electrolyser-telemetry-main/
├── .env.example                  # Secret template (copy → .env)
├── .github/workflows/ci.yml      # GitHub Actions CI (lint + test)
├── Makefile                      # All developer tasks
├── docker-compose.yml            # Full stack container definitions
├── schemas/
│   └── telemetry_v1.json         # JSON Schema for MQTT payload validation
├── clients/python/
│   ├── plant_sim.py              # Digital-twin simulator (main entry point)
│   ├── sensor_client.py          # Standalone sensor publisher
│   ├── launch_sensors.py         # Batch sensor launcher
│   └── requirements.txt          # Python dependencies
├── scripts/
│   ├── export_dataset.py         # Labelled dataset exporter
│   ├── test_faults.py            # Automated fault verification
│   ├── generate-acl.sh           # ACL file generator
│   └── pki/                      # PKI scripts (CA, broker, client, rotate)
├── tests/
│   ├── test_physics.py           # 30+ unit tests (no broker required)
│   └── test_schema.py            # Schema validation test
├── mosquitto/conf/mosquitto.conf # Broker: TLS 1.3, cert auth, ACL
├── telegraf/telegraf.conf        # MQTT → InfluxDB pipeline
├── notebooks/
│   └── anomaly_detection.ipynb  # Isolation Forest + Random Forest
└── web_simulation/               # React SCADA interface
    └── src/
        ├── App.jsx               # MQTT WebSocket connection
        └── components/           # P&ID: Stack, Tank, Pump, Pipe, DigitalTwin
```

---

## Authors

- N. Ragavenderan (1RV22CS122)
- Rishabh Kumar Lal (1RV22CS159)
- Manas Sakthivel (1RV22CS103)
- Mohammed Ilham (1RV22CS117)

RV College of Engineering, Bengaluru — CS375TGD, 2025–26

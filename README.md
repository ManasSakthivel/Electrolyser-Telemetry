# Electrolyser Telemetry System

[![CI](https://github.com/ManasSakthivel/Electrolyser-Telemetry/actions/workflows/ci.yml/badge.svg)](https://github.com/ManasSakthivel/Electrolyser-Telemetry/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%20|%203.12-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-54%20passed-brightgreen)](#running-tests)

An IoT telemetry platform for monitoring green hydrogen electrolyser plants, built as a learning project in systems integration and ML. The system covers five layers — physics simulation, secured MQTT transport, time-series ingestion, real-time visualisation, and ML-based fault detection — all running in Docker.

---

## System Architecture

The platform is organised as a five-layer pipeline. Each layer is independently deployable and communicates over authenticated, encrypted channels.

<p align="center">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 540" width="720" height="540" font-family="-apple-system,Segoe UI,sans-serif" font-size="13">
  <!-- Layer 1: Simulation -->
  <rect x="20" y="20" width="680" height="80" rx="8" fill="#e8f4fd" stroke="#3b82d4" stroke-width="1.5"/>
  <text x="36" y="45" font-weight="bold" fill="#1f2328" font-size="14">LAYER 1 — SIMULATION</text>
  <text x="36" y="64" fill="#57606a">Physics-based digital twin (EL1, EL2) · Butler-Volmer + Nernst + Ohmic voltage model</text>
  <text x="36" y="83" fill="#57606a">16 injectable fault modes · 1 Hz telemetry · PV irradiance · per-sensor X.509 mTLS</text>
  <text x="610" y="64" fill="#3b82d4" font-size="11">plant_sim.py</text>

  <!-- Arrow 1→2 -->
  <line x1="360" y1="100" x2="360" y2="130" stroke="#57606a" stroke-width="1.5" marker-end="url(#arr)"/>
  <text x="370" y="120" fill="#57606a" font-size="11">MQTT QoS-1 · mTLS (X.509 per device) · port 8883</text>

  <!-- Layer 2: Security -->
  <rect x="20" y="130" width="680" height="80" rx="8" fill="#fef3e2" stroke="#d97706" stroke-width="1.5"/>
  <text x="36" y="155" font-weight="bold" fill="#1f2328" font-size="14">LAYER 2 — ZERO-TRUST SECURITY</text>
  <text x="36" y="174" fill="#57606a">Eclipse Mosquitto 2.0 · TLS 1.3 · per-sensor X.509 certificates signed by plant CA</text>
  <text x="36" y="193" fill="#57606a">ACL-based topic authorisation (each sensor publishes to its own topic only) · automated cert rotation</text>
  <text x="575" y="174" fill="#d97706" font-size="11">mosquitto.conf</text>

  <!-- Arrow 2→3 -->
  <line x1="360" y1="210" x2="360" y2="240" stroke="#57606a" stroke-width="1.5" marker-end="url(#arr)"/>
  <text x="370" y="230" fill="#57606a" font-size="11">MQTT subscribe (mTLS) · Telegraf consumer</text>

  <!-- Layer 3: Ingestion -->
  <rect x="20" y="240" width="680" height="80" rx="8" fill="#f0fdf4" stroke="#16a34a" stroke-width="1.5"/>
  <text x="36" y="265" font-weight="bold" fill="#1f2328" font-size="14">LAYER 3 — INGESTION &amp; STORAGE</text>
  <text x="36" y="284" fill="#57606a">Telegraf 1.31 parses JSON payloads → InfluxDB 2.7 time-series bucket</text>
  <text x="36" y="303" fill="#57606a">Tag schema: el · sensor · cell · unit · 1 s write interval · Flux query interface</text>
  <text x="575" y="284" fill="#16a34a" font-size="11">telegraf.conf</text>

  <!-- Arrow 3→4 -->
  <line x1="360" y1="320" x2="360" y2="350" stroke="#57606a" stroke-width="1.5" marker-end="url(#arr)"/>
  <text x="370" y="340" fill="#57606a" font-size="11">Flux queries · WebSocket MQTT (port 9001)</text>

  <!-- Layer 4: Visualisation -->
  <rect x="20" y="350" width="680" height="80" rx="8" fill="#fdf4ff" stroke="#7c5cd8" stroke-width="1.5"/>
  <text x="36" y="375" font-weight="bold" fill="#1f2328" font-size="14">LAYER 4 — VISUALISATION</text>
  <text x="36" y="394" fill="#57606a">Grafana dashboards · React 19 SCADA P&amp;ID (WebSocket MQTT, port 9001)</text>
  <text x="36" y="413" fill="#57606a">Real-time stack/cell/flow/pressure indicators · live fault state overlays</text>
  <text x="553" y="394" fill="#7c5cd8" font-size="11">web_simulation/</text>

  <!-- Arrow 4→5 -->
  <line x1="360" y1="430" x2="360" y2="460" stroke="#57606a" stroke-width="1.5" marker-end="url(#arr)"/>
  <text x="370" y="450" fill="#57606a" font-size="11">Parquet export · export_dataset.py</text>

  <!-- Layer 5: ML -->
  <rect x="20" y="460" width="680" height="65" rx="8" fill="#fef2f2" stroke="#dc2626" stroke-width="1.5"/>
  <text x="36" y="485" font-weight="bold" fill="#1f2328" font-size="14">LAYER 5 — ML FAULT DETECTION</text>
  <text x="36" y="504" fill="#57606a">Isolation Forest (unsupervised) · Random Forest (16-class) · LSTM Autoencoder</text>
  <text x="36" y="520" fill="#57606a">Ablation study · alarm lead-time experiment · 16,000-row synthetic dataset</text>
  <text x="505" y="504" fill="#dc2626" font-size="11">anomaly_detection.ipynb</text>

  <!-- Arrow marker -->
  <defs>
    <marker id="arr" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
      <path d="M0,0 L0,6 L8,3 z" fill="#57606a"/>
    </marker>
  </defs>
</svg>
</p>

---

## Security Architecture

Every device in the system holds a unique X.509 certificate signed by the plant's self-managed CA. The broker refuses connections that cannot present a valid certificate. Topic-level ACLs prevent any sensor from publishing to another sensor's topic — a zero-trust posture for IIoT.

<p align="center">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 700 220" width="700" height="220" font-family="-apple-system,Segoe UI,sans-serif" font-size="12">
  <!-- CA box -->
  <rect x="255" y="10" width="190" height="50" rx="6" fill="#e8f4fd" stroke="#3b82d4" stroke-width="1.5"/>
  <text x="350" y="33" text-anchor="middle" font-weight="bold" fill="#1f2328">Certificate Authority</text>
  <text x="350" y="51" text-anchor="middle" fill="#57606a">certs/ca/ca.crt  (self-signed root)</text>

  <!-- Lines from CA -->
  <line x1="280" y1="60" x2="100" y2="120" stroke="#57606a" stroke-width="1.2"/>
  <line x1="350" y1="60" x2="350" y2="120" stroke="#57606a" stroke-width="1.2"/>
  <line x1="420" y1="60" x2="540" y2="120" stroke="#57606a" stroke-width="1.2"/>
  <line x1="350" y1="60" x2="620" y2="120" stroke="#57606a" stroke-width="1.2" stroke-dasharray="4,3"/>

  <!-- Broker cert -->
  <rect x="20" y="120" width="165" height="50" rx="6" fill="#fef3e2" stroke="#d97706" stroke-width="1.2"/>
  <text x="103" y="141" text-anchor="middle" font-weight="bold" fill="#1f2328">broker.crt</text>
  <text x="103" y="158" text-anchor="middle" fill="#57606a">Mosquitto server</text>

  <!-- Sensor cert -->
  <rect x="260" y="120" width="180" height="50" rx="6" fill="#f0fdf4" stroke="#16a34a" stroke-width="1.2"/>
  <text x="350" y="141" text-anchor="middle" font-weight="bold" fill="#1f2328">sensor-EL1-cell_1.crt</text>
  <text x="350" y="158" text-anchor="middle" fill="#57606a">one per sensor (26 total)</text>

  <!-- Telegraf cert -->
  <rect x="460" y="120" width="165" height="50" rx="6" fill="#fdf4ff" stroke="#7c5cd8" stroke-width="1.2"/>
  <text x="543" y="141" text-anchor="middle" font-weight="bold" fill="#1f2328">telegraf-subscriber.crt</text>
  <text x="543" y="158" text-anchor="middle" fill="#57606a">Telegraf consumer</text>

  <!-- ACL legend -->
  <rect x="20" y="185" width="660" height="25" rx="4" fill="#f7f8fa" stroke="#e5e7eb" stroke-width="1"/>
  <text x="350" y="202" text-anchor="middle" fill="#57606a">ACL enforced: each sensor CN may only publish to electrolyser/plant-A/{EL}/{sensor}/… · TLS 1.3 on all ports</text>
</svg>
</p>

**Security controls enforced by the broker:**

| Control | Detail |
|---|---|
| Transport | TLS 1.3 on all connections (port 8883 mTLS, port 9001 TLS WebSocket) |
| Authentication | Certificate-based — CN extracted as MQTT username; no password auth |
| Authorisation | Per-sensor ACL — each sensor may only publish to its own topic path |
| Cert rotation | `./scripts/pki/rotate-cert.sh [CN\|all]` — zero-downtime rolling rotation |
| Secrets | All credentials in `.env` (never committed); `.env.example` as template |

---

## ML Fault Detection Pipeline

<p align="center">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 310" width="720" height="310" font-family="-apple-system,Segoe UI,sans-serif" font-size="12">
  <defs>
    <marker id="arr2" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
      <path d="M0,0 L0,6 L8,3 z" fill="#57606a"/>
    </marker>
  </defs>

  <!-- Dataset box -->
  <rect x="220" y="10" width="280" height="45" rx="6" fill="#e8f4fd" stroke="#3b82d4" stroke-width="1.5"/>
  <text x="360" y="30" text-anchor="middle" font-weight="bold" fill="#1f2328">data/telemetry_labelled.parquet</text>
  <text x="360" y="48" text-anchor="middle" fill="#57606a">16,000 rows · 16 fault classes · 500 rows/class</text>

  <!-- Arrow down to feature eng -->
  <line x1="360" y1="55" x2="360" y2="85" stroke="#57606a" stroke-width="1.5" marker-end="url(#arr2)"/>

  <!-- Feature engineering -->
  <rect x="180" y="85" width="360" height="55" rx="6" fill="#f7f8fa" stroke="#e5e7eb" stroke-width="1.5"/>
  <text x="360" y="106" text-anchor="middle" font-weight="bold" fill="#1f2328">Feature Engineering</text>
  <text x="360" y="123" text-anchor="middle" fill="#57606a">Raw: 14 sensor channels · Derived: cell_voltage_std, H₂/O₂ ratio,</text>
  <text x="360" y="138" text-anchor="middle" fill="#57606a">stack_power, cell_voltage_min/max · StandardScaler normalisation</text>

  <!-- Three branches -->
  <line x1="240" y1="140" x2="110" y2="185" stroke="#57606a" stroke-width="1.2" marker-end="url(#arr2)"/>
  <line x1="360" y1="140" x2="360" y2="185" stroke="#57606a" stroke-width="1.2" marker-end="url(#arr2)"/>
  <line x1="480" y1="140" x2="600" y2="185" stroke="#57606a" stroke-width="1.2" marker-end="url(#arr2)"/>

  <!-- Isolation Forest -->
  <rect x="20" y="185" width="185" height="65" rx="6" fill="#fef3e2" stroke="#d97706" stroke-width="1.2"/>
  <text x="113" y="207" text-anchor="middle" font-weight="bold" fill="#1f2328">Isolation Forest</text>
  <text x="113" y="224" text-anchor="middle" fill="#57606a">Unsupervised · trained</text>
  <text x="113" y="240" text-anchor="middle" fill="#57606a">on normal data only</text>

  <!-- Random Forest -->
  <rect x="270" y="185" width="185" height="65" rx="6" fill="#f0fdf4" stroke="#16a34a" stroke-width="1.2"/>
  <text x="363" y="207" text-anchor="middle" font-weight="bold" fill="#1f2328">Random Forest</text>
  <text x="363" y="224" text-anchor="middle" fill="#57606a">Supervised · 16-class</text>
  <text x="363" y="240" text-anchor="middle" fill="#57606a">5-fold CV · SHAP explainability</text>

  <!-- LSTM Autoencoder -->
  <rect x="515" y="185" width="185" height="65" rx="6" fill="#fdf4ff" stroke="#7c5cd8" stroke-width="1.2"/>
  <text x="608" y="207" text-anchor="middle" font-weight="bold" fill="#1f2328">LSTM Autoencoder</text>
  <text x="608" y="224" text-anchor="middle" fill="#57606a">Temporal patterns · recon-</text>
  <text x="608" y="240" text-anchor="middle" fill="#57606a">struction error threshold</text>

  <!-- Bottom bar: ablation + lead time -->
  <rect x="20" y="270" width="680" height="30" rx="5" fill="#f7f8fa" stroke="#e5e7eb" stroke-width="1"/>
  <text x="360" y="290" text-anchor="middle" fill="#57606a">Section 6: Ablation study (feature group removal) · Section 7: Lead-time experiment — LSTM vs threshold alarm (15 fault classes)</text>
</svg>
</p>

### Physics Validation

The digital twin's polarisation curve is validated against two independent datasets:

| Model | RMSE vs Monopoli et al. 2023 | RMSE vs Koch et al. 2024 |
|---|---|---|
| Three-term (BV + Conc + Ohmic) | **measured at runtime** | **measured at runtime** |
| Two-term (BV + Ohmic) | higher | — |
| Ohmic-only | highest | — |

Run `python scripts/validate_physics.py` to reproduce. The three-term model uses **scipy L-BFGS-B** parameter fitting and is validated on the Koch et al. 2024 dataset which was not used during fitting.

---

## Key Software Components

| Component | Technology | Purpose |
|---|---|---|
| [`plant_sim.py`](clients/python/plant_sim.py) | Python 3.11, paho-mqtt | Physics-based digital twin (EL1, EL2); Butler-Volmer + Nernst + Ohmic; 16 fault modes; per-device mTLS |
| [`sensor_client.py`](clients/python/sensor_client.py) | Python 3.11 | Standalone single-sensor publisher (mTLS) |
| [`export_dataset.py`](scripts/export_dataset.py) | Python, pandas, pyarrow | Labelled telemetry → Parquet/CSV; 500 rows/class; manufacturing spread injected |
| [`validate_physics.py`](scripts/validate_physics.py) | Python, scipy, matplotlib | Three-model polarisation curve comparison; Koch et al. 2024 independent validation |
| [`leadtime_experiment.py`](scripts/leadtime_experiment.py) | Python, torch, sklearn | LSTM Autoencoder vs threshold alarm lead-time measurement per fault class |
| [`benchmark_latency.py`](scripts/benchmark_latency.py) | Python, paho-mqtt | End-to-end MQTT latency benchmarking; localhost vs Docker bridge comparison |
| [`anomaly_detection.ipynb`](notebooks/anomaly_detection.ipynb) | scikit-learn, torch, SHAP | Isolation Forest + Random Forest + LSTM; ablation study; lead-time analysis |
| [`mosquitto.conf`](mosquitto/conf/mosquitto.conf) | Mosquitto 2.0 | TLS 1.3, cert auth, per-topic ACL, hardened broker |
| [`telegraf.conf`](telegraf/telegraf.conf) | Telegraf 1.31 | mTLS MQTT subscribe → InfluxDB v2 write |
| [`docker-compose.yml`](docker-compose.yml) | Docker Compose | Full stack: Mosquitto + InfluxDB + Telegraf + Grafana |
| [`web_simulation/`](web_simulation/) | React 19, Vite, TailwindCSS | Real-time SCADA P&ID dashboard (MQTT WebSocket, port 9001) |
| [`tests/`](tests/) | pytest | **54 unit tests** — physics, faults, schema, topic resolution, concentration overpotential |
| [`.github/workflows/ci.yml`](.github/workflows/ci.yml) | GitHub Actions | Multi-version CI (3.11 + 3.12): lint (ruff) + test (pytest) + notebook smoke test |

---

## MQTT Topic Namespace

```
electrolyser/
└── plant-A/
    ├── EL1/
    │   ├── cell/{1-5}/voltage        (V)     — 5 independent cell measurements
    │   ├── stack/current             (A)
    │   ├── stack/temperature         (°C)
    │   ├── stack/pressure            (bar)
    │   ├── h2/flow_rate              (L/min)
    │   ├── o2/flow_rate              (L/min)
    │   ├── tank/pressure             (bar)
    │   ├── water_flow                (L/min)
    │   └── status                    (JSON: OPERATIONAL | TRIPPED)
    ├── EL2/ (same structure)
    └── irradiance/{1,2}              (W/m²)  — PV irradiance sensors
control/
└── faults                            (JSON fault injection commands)
```

Each sensor has a **dedicated MQTT client** with its own X.509 certificate. The broker's ACL file (auto-generated by `scripts/generate-acl.sh`) ties each certificate CN to exactly one topic prefix.

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

### 2. Start the full stack

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

### 5. Inject a fault

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
# Writes data/telemetry_labelled.parquet + .csv (16,000 rows, 16 classes)
```

### 7. Run the ML pipeline

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

**54 tests** covering:

- Butler-Volmer activation overpotential formula correctness
- Nernst concentration overpotential (7 dedicated tests)
- Monotonicity of stack voltage with current
- All 16 fault modes produce expected telemetry signatures (no live broker required)
- JSON schema validation (valid payload, missing field, invalid enum)
- MQTT topic resolution for all sensor types
- Sensor value ranges for all sensor types
- Polarisation curve RMSE thresholds (Monopoli, NREL datasets)
- Physics model parameter consistency

---

## Fault Simulation

The fault injection harness supports **16 modes**, all triggerable over MQTT at runtime without restarting the simulator:

| Fault | Observable Signature |
|---|---|
| `membrane_pinhole` | Cell 1 voltage +500 mV, H₂ flow +20% |
| `gas_crossover` | H₂/O₂ ratio deviates from 2.0 (< 1.9 or > 2.1) |
| `cell_flooding` | Cells 3–4 drop below 1.4 V |
| `cell_dryout` | All cells above 2.2 V, temperature rising |
| `pump_failure` | Water flow = 0 L/min |
| `dcdc_failure` | Stack current = 0, open-circuit voltage |
| `over_pressure` | Tank pressure spikes to 40 bar |
| `solar_transient` | Periodic current spike above 600 A |
| `loose_bolt` | Current 25% below expected |
| `o2_blockage` | O₂ flow drops to 20% of nominal |
| `voltage_sensor_drift` | Cell 5 stuck at 0.0 V |
| `temp_sensor_failure` | Temperature stuck at 0.0 °C |
| `irradiance_drift` | Irradiance sensor 1 diverges by more than 300 W/m² |
| `level_sensor` | Tank pressure noisy (±2 bar random walk) |
| `telemetry_dropout` | No MQTT messages published for the electrolyser |
| `none` | Clear all active faults |

---

## Makefile Targets

```
make setup              — Generate all PKI certificates
make up / down          — Start / stop Docker stack
make sim                — Run digital-twin simulator
make export             — Export 16,000-row labelled Parquet dataset
make test               — Run 54 pytest unit tests
make lint               — ruff check (matches CI)
make validate-physics   — Three-term vs Koch et al. polarisation curve comparison
make leadtime-experiment — LSTM vs threshold alarm lead-time per fault class
make ablation           — Feature ablation study in notebook
make benchmark          — End-to-end MQTT latency (localhost)
make benchmark-bridge   — End-to-end MQTT latency (Docker bridge)
```

---

## Project Structure

```
electrolyser-telemetry-main/
├── .env.example                       # Secret template (copy → .env)
├── .github/workflows/ci.yml           # GitHub Actions CI: lint + test + notebook smoke
├── Makefile                           # All developer tasks (15+ targets)
├── docker-compose.yml                 # Full stack container definitions
├── schemas/
│   └── telemetry_v1.json              # JSON Schema for MQTT payload validation
├── clients/python/
│   ├── plant_sim.py                   # Digital-twin simulator — main entry point
│   ├── sensor_client.py               # Standalone sensor publisher
│   ├── launch_sensors.py              # Batch sensor launcher
│   ├── telemetry_types.py             # Typed dataclasses for telemetry payloads
│   └── requirements.txt               # Python dependencies (incl. scipy, torch, shap)
├── scripts/
│   ├── export_dataset.py              # Labelled dataset exporter (500 rows/class)
│   ├── validate_physics.py            # Polarisation curve validation vs Koch et al. 2024
│   ├── leadtime_experiment.py         # LSTM vs threshold alarm lead-time experiment
│   ├── benchmark_latency.py           # End-to-end MQTT latency benchmarking
│   ├── test_faults.py                 # Automated fault verification (live broker)
│   ├── generate-acl.sh                # ACL file generator
│   └── pki/                           # PKI scripts (CA, broker, client, rotate)
├── tests/
│   ├── test_physics.py                # 47 unit tests — physics, faults, schema, sensors
│   ├── test_physics_validation.py     # 7 polarisation curve validation tests
│   └── test_schema.py                 # JSON schema validation
├── mosquitto/conf/mosquitto.conf      # Broker: TLS 1.3, cert auth, per-topic ACL
├── telegraf/telegraf.conf             # MQTT → InfluxDB 2.7 pipeline
├── notebooks/
│   └── anomaly_detection.ipynb        # ML pipeline: IF + RF + LSTM + ablation + lead-time
└── web_simulation/                    # React 19 SCADA interface
    └── src/
        ├── App.jsx                    # MQTT WebSocket connection manager
        └── components/                # P&ID: Stack, Tank, Pump, Pipe, DigitalTwin
```

---

## Author

**Manas Sakthivel**  
RV College of Engineering, Bengaluru — CS375TGD, 2025–26  
[github.com/ManasSakthivel](https://github.com/ManasSakthivel)

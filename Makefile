SHELL := /bin/bash
.DEFAULT_GOAL := help

# ── Colours ───────────────────────────────────────────────────────────────────
BOLD  := $(shell tput bold 2>/dev/null || echo "")
RESET := $(shell tput sgr0 2>/dev/null || echo "")

.PHONY: help setup ca broker clients acl up init-pwfile down logs sim test lint export export-synthetic benchmark benchmark-bridge validate-physics leadtime-experiment ablation notebook pipeline clean

help:
	@echo ""
	@echo "$(BOLD)Electrolyser Telemetry — Make targets$(RESET)"
	@echo ""
	@echo "  $(BOLD)setup$(RESET)               Bootstrap full PKI + ACL (run once)"
	@echo "  $(BOLD)ca$(RESET)                  Create Certificate Authority"
	@echo "  $(BOLD)broker$(RESET)              Create broker TLS certificate"
	@echo "  $(BOLD)clients$(RESET)             Create all per-sensor client certificates"
	@echo "  $(BOLD)acl$(RESET)                 Regenerate mosquitto ACL file"
	@echo ""
	@echo "  $(BOLD)up$(RESET)                  Start full Docker stack (broker + influx + telegraf + grafana)"
	@echo "  $(BOLD)init-pwfile$(RESET)         Add WebSocket viewer (ws_viewer) to Mosquitto password file (run once after 'make up')"
	@echo "  $(BOLD)down$(RESET)                Stop Docker stack"
	@echo "  $(BOLD)logs$(RESET)                Tail logs from all containers"
	@echo ""
	@echo "  $(BOLD)sim$(RESET)                 Run plant digital-twin simulator (requires stack up)"
	@echo "  $(BOLD)test$(RESET)                Run unit tests with pytest (no broker needed)"
	@echo "  $(BOLD)lint$(RESET)                Lint Python sources with ruff"
	@echo "  $(BOLD)export$(RESET)              Export labelled dataset — live (600 s, broker required)"
	@echo "  $(BOLD)export-synthetic$(RESET)    Generate synthetic dataset without broker"
	@echo "  $(BOLD)benchmark$(RESET)           Measure MQTT latency p50/p95/p99 — localhost (broker required)"
	@echo "  $(BOLD)benchmark-bridge$(RESET)    Measure MQTT latency across Docker bridge (IEC-grade)"
	@echo "  $(BOLD)validate-physics$(RESET)    Three-term BV model vs published PEM reference curves + Koch et al."
	@echo "  $(BOLD)leadtime-experiment$(RESET) LSTM vs threshold alarm lead-time experiment (no broker)"
	@echo "  $(BOLD)ablation$(RESET)            Feature ablation: raw vs engineered features"
	@echo "  $(BOLD)notebook$(RESET)            Execute full ML notebook (ablation + lead-time included)"
	@echo "  $(BOLD)pipeline$(RESET)            Run full offline pipeline (no broker needed)"
	@echo "  $(BOLD)clean$(RESET)               Remove caches + generated artefacts"
	@echo ""

# ── PKI ───────────────────────────────────────────────────────────────────────
setup: ca broker clients acl
	@echo "$(BOLD)Setup complete.$(RESET)  Run 'make up' then 'make sim'."

ca:
	@echo "Creating Certificate Authority…"
	./scripts/pki/make-ca.sh

broker: ca
	@echo "Creating broker certificate…"
	./scripts/pki/make-broker.sh

clients: ca
	@echo "Creating all per-sensor client certificates…"
	./scripts/pki/make-clients-batch.sh
	@echo "Creating telegraf-subscriber certificate…"
	./scripts/pki/make-client.sh telegraf-subscriber
	@echo "Creating monitor-local certificate…"
	./scripts/pki/make-client.sh monitor-local

acl:
	@echo "Generating ACL file…"
	./scripts/generate-acl.sh

single-client: ca
	@if [ -z "$$CN" ]; then echo "Usage: make single-client CN=sensor-EL1-cell_1_voltage"; exit 1; fi
	./scripts/pki/make-client.sh "$$CN"

# ── Docker stack ──────────────────────────────────────────────────────────────
up:
	@if [ ! -f .env ]; then \
	  echo "$(BOLD)ERROR:$(RESET) .env not found. Copy .env.example → .env and fill in secrets."; exit 1; fi
	docker compose up -d --remove-orphans

init-pwfile:
	@if [ ! -f .env ]; then \
	  echo "$(BOLD)ERROR:$(RESET) .env not found. Copy .env.example → .env and fill in secrets."; exit 1; fi
	set -a; . ./.env; set +a; ./scripts/init-pwfile.sh

down:
	docker compose down

logs:
	docker compose logs -f

# ── Simulation ────────────────────────────────────────────────────────────────
.venv/bin/activate:
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -r clients/python/requirements.txt

sim: .venv/bin/activate
	. .venv/bin/activate && python clients/python/plant_sim.py

# ── Quality ───────────────────────────────────────────────────────────────────
test: .venv/bin/activate
	. .venv/bin/activate && pytest tests/ -v --tb=short

lint: .venv/bin/activate
	. .venv/bin/activate && pip install -q ruff && ruff check clients/python/ scripts/ tests/ --ignore E501

# ── Dataset export ────────────────────────────────────────────────────────────
export: .venv/bin/activate
	@echo "$(BOLD)Live export$(RESET) — collecting 600 s from running simulator …"
	@echo "  Tip: run 'make sim' in a separate terminal first."
	. .venv/bin/activate && python scripts/export_dataset.py --duration 600 --out data/telemetry_labelled.parquet

export-synthetic: .venv/bin/activate
	@echo "$(BOLD)Synthetic export$(RESET) — generating 500 rows/class (±15% R_ohm, η_F spread, membrane drift) …"
	. .venv/bin/activate && python scripts/export_dataset.py --synthetic --rows 500 --out data/telemetry_labelled.parquet

# ── Latency benchmark ─────────────────────────────────────────────────────────
benchmark: .venv/bin/activate
	@echo "$(BOLD)Latency benchmark (localhost)$(RESET) — 200 round-trips (requires broker running) …"
	. .venv/bin/activate && python scripts/benchmark_latency.py --n 200 --out data --network-label localhost

benchmark-bridge: .venv/bin/activate
	@echo "$(BOLD)Latency benchmark (Docker bridge)$(RESET) — run this from inside the telemetry_net network"
	@echo "  docker run --rm --network electrolyser-telemetry-main_telemetry_net \\"
	@echo "    -v \$$(pwd)/certs:/app/certs -v \$$(pwd)/data:/app/data \\"
	@echo "    python:3.11-slim bash -c 'pip install paho-mqtt matplotlib && \\"
	@echo "      python scripts/benchmark_latency.py --broker broker --n 200 --network-label docker-bridge'"
	@echo ""
	@echo "  Or if running natively with broker on docker bridge IP:"
	. .venv/bin/activate && python scripts/benchmark_latency.py --n 200 \
	  --broker $$(docker inspect mosquitto --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' 2>/dev/null || echo "127.0.0.1") \
	  --out data --network-label docker-bridge

# ── Physics validation ────────────────────────────────────────────────────────
validate-physics: .venv/bin/activate
	@echo "$(BOLD)Physics validation$(RESET) — three-term model vs Monopoli + NREL (training) + Koch et al. (independent) …"
	. .venv/bin/activate && pip install -q matplotlib numpy scipy && python scripts/validate_physics.py

# ── Lead-time experiment ──────────────────────────────────────────────────────
leadtime-experiment: .venv/bin/activate
	@echo "$(BOLD)LSTM lead-time experiment$(RESET) — LSTM vs threshold alarm per fault class …"
	. .venv/bin/activate && pip install -q torch scikit-learn && \
	  python scripts/leadtime_experiment.py --rows 300 --window 30 --epochs 30 --out data/leadtime_experiment.json

# ── Ablation target (runs notebook, which contains the ablation cell) ─────────
ablation: notebook
	@echo "Ablation results embedded in executed notebook and data/ablation_study.png"

# ── ML notebook ───────────────────────────────────────────────────────────────
notebook: .venv/bin/activate export-synthetic
	@echo "$(BOLD)Executing ML notebook$(RESET) — requires jupyter nbconvert …"
	. .venv/bin/activate && pip install -q jupyter nbconvert && \
	  jupyter nbconvert --to notebook --execute \
	    --ExecutePreprocessor.timeout=300 \
	    --output notebooks/anomaly_detection_executed.ipynb \
	    notebooks/anomaly_detection.ipynb
	@echo "Executed notebook saved → notebooks/anomaly_detection_executed.ipynb"

# ── Full pipeline (one-shot) ──────────────────────────────────────────────────
pipeline: .venv/bin/activate
	@echo "$(BOLD)Full pipeline$(RESET): export-synthetic → validate-physics → leadtime-experiment → test → notebook"
	$(MAKE) export-synthetic
	$(MAKE) validate-physics
	$(MAKE) leadtime-experiment
	$(MAKE) test
	$(MAKE) notebook
	@echo "$(BOLD)Pipeline complete.$(RESET)"

# ── Housekeeping ──────────────────────────────────────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache .coverage htmlcov data/*.png data/*.json \
	       notebooks/anomaly_detection_executed.ipynb

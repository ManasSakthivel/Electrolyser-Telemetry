#!/usr/bin/env bash
# =============================================================================
# run_pipeline.sh
# ===============
# One-shot script that runs the complete electrolyser telemetry pipeline.
#
# Offline mode (no broker required — default):
#   ./scripts/run_pipeline.sh
#
# Online mode (uses live MQTT broker):
#   ./scripts/run_pipeline.sh --live
#
# Steps
# -----
#   1. Check / create Python virtual environment
#   2. Install dependencies
#   3. Generate synthetic dataset (or collect from live broker)
#   4. Validate Butler-Volmer physics model vs reference data
#   5. Run all 47 unit tests
#   6. Execute ML notebook (saves figures + model_comparison.csv)
#   7. Run MQTT latency benchmark (online mode only)
#
# Output artefacts (all in data/)
# --------------------------------
#   telemetry_labelled.parquet / .csv    — labelled dataset
#   physics_validation_report.json       — RMSE vs Monopoli + NREL
#   polarisation_curve_comparison.png    — polarisation curve plot
#   model_comparison.csv                 — ML results table
#   latency_report.json                  — MQTT latency stats (online only)
#   latency_histogram.png                — latency distribution (online only)
#   ../notebooks/anomaly_detection_executed.ipynb  — executed notebook
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT}"

LIVE=false
for arg in "$@"; do
  [[ "$arg" == "--live" ]] && LIVE=true
done

# ── Colour helpers ────────────────────────────────────────────────────────────
BOLD=$(tput bold 2>/dev/null || echo "")
RESET=$(tput sgr0 2>/dev/null || echo "")
GREEN=$(tput setaf 2 2>/dev/null || echo "")
YELLOW=$(tput setaf 3 2>/dev/null || echo "")

step() { echo ""; echo "${BOLD}${GREEN}▶ $*${RESET}"; }
warn() { echo "${YELLOW}⚠  $*${RESET}"; }

# ── Step 1: Virtual environment ───────────────────────────────────────────────
step "1/7  Setting up Python virtual environment"
if [[ ! -f .venv/bin/activate ]]; then
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip --quiet
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# ── Step 2: Install dependencies ─────────────────────────────────────────────
step "2/7  Installing Python dependencies"
pip install -q -r clients/python/requirements.txt
pip install -q matplotlib numpy jupyter nbconvert

# ── Step 3: Dataset ───────────────────────────────────────────────────────────
if [[ "$LIVE" == "true" ]]; then
    step "3/7  Collecting live dataset (600 s) — broker must be running"
    warn "Make sure 'make sim' is running in a separate terminal."
    python scripts/export_dataset.py \
        --duration 600 \
        --out data/telemetry_labelled.parquet
else
    step "3/7  Generating synthetic dataset (no broker needed)"
    python scripts/export_dataset.py \
        --synthetic \
        --rows 80 \
        --seed 42 \
        --out data/telemetry_labelled.parquet
fi

# ── Step 4: Physics validation ────────────────────────────────────────────────
step "4/7  Validating Butler-Volmer physics model vs published PEM data"
python scripts/validate_physics.py

# ── Step 5: Unit tests ────────────────────────────────────────────────────────
step "5/7  Running unit tests (47 tests)"
pytest tests/ -v --tb=short

# ── Step 6: ML notebook ───────────────────────────────────────────────────────
step "6/7  Executing ML notebook"
jupyter nbconvert \
    --to notebook \
    --execute \
    --ExecutePreprocessor.timeout=600 \
    --output notebooks/anomaly_detection_executed.ipynb \
    notebooks/anomaly_detection.ipynb

echo ""
echo "  ML results saved → data/model_comparison.csv"
echo "  Executed notebook → notebooks/anomaly_detection_executed.ipynb"

# ── Step 7: Latency benchmark (online only) ───────────────────────────────────
if [[ "$LIVE" == "true" ]]; then
    step "7/7  Running MQTT latency benchmark (200 round-trips)"
    python scripts/benchmark_latency.py --n 200 --out data
else
    step "7/7  Skipping latency benchmark (offline mode — use --live to enable)"
    warn "To measure latency: make up && make benchmark"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "${BOLD}${GREEN}Pipeline complete!${RESET}"
echo ""
echo "  Artefacts in data/:"
ls -lh data/ 2>/dev/null | grep -v "^total" || true
echo ""
echo "  To view ML results:"
echo "    cat data/model_comparison.csv"
echo ""
echo "  To open notebook:"
echo "    jupyter notebook notebooks/anomaly_detection_executed.ipynb"

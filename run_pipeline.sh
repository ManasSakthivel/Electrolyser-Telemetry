#!/bin/bash

# Electrolyser Early Fault Prediction - Complete Pipeline
# Runs: Data Generation → Feature Engineering → Training → Validation

set -e  # Exit on error

echo "================================================================================"
echo "ELECTROLYSER EARLY FAULT PREDICTION PIPELINE"
echo "================================================================================"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: python3 not found"
    exit 1
fi

echo "✅ Python found: $(python3 --version)"
echo ""

# Check dependencies
echo "Checking dependencies..."
python3 -c "import pandas, numpy, sklearn, xgboost" 2>/dev/null
if [ $? -eq 0 ]; then
    echo "✅ All dependencies installed"
else
    echo "❌ Missing dependencies. Run: pip install -r requirements.txt"
    exit 1
fi
echo ""

# Create output directories
mkdir -p data/generated
mkdir -p research/results
mkdir -p ml/models

echo "================================================================================"
echo "STEP 1: DATA GENERATION"
echo "================================================================================"
echo "Generating dataset from digital twin simulation..."
echo ""

python3 data_generation/dataset_generator.py

if [ $? -ne 0 ]; then
    echo "❌ Data generation failed"
    exit 1
fi

echo ""
echo "✅ Dataset generated successfully"
echo ""

echo "================================================================================"
echo "STEP 2: FEATURE ENGINEERING"
echo "================================================================================"
echo "Engineering features from raw sensor data..."
echo ""

python3 ml/feature_engineering.py

if [ $? -ne 0 ]; then
    echo "❌ Feature engineering failed"
    exit 1
fi

echo ""
echo "✅ Features engineered successfully"
echo ""

echo "================================================================================"
echo "STEP 3: MODEL TRAINING & EVALUATION"
echo "================================================================================"
echo "Training early fault prediction models..."
echo ""

python3 ml/train_and_evaluate.py

if [ $? -ne 0 ]; then
    echo "❌ Training failed"
    exit 1
fi

echo ""
echo "✅ Models trained successfully"
echo ""

echo "================================================================================"
echo "STEP 4: COMPREHENSIVE VALIDATION"
echo "================================================================================"
echo "Running validation suite (EDT, robustness, ablation, generalization)..."
echo ""

python3 experiments/validation_suite.py \
    --dataset data/generated/dataset_v1.csv \
    --model research/results/xgboost_model.joblib

if [ $? -ne 0 ]; then
    echo "❌ Validation failed"
    exit 1
fi

echo ""
echo "✅ Validation complete"
echo ""

echo "================================================================================"
echo "PIPELINE COMPLETE ✅"
echo "================================================================================"
echo ""
echo "Results saved to:"
echo "  📊 research/results/metrics.json"
echo "  📈 research/results/early_prediction_timeline.png"
echo "  📉 research/results/edt_distribution.png"
echo "  📋 research/results/early_detection_metrics.json"
echo ""
echo "To view results:"
echo "  cat research/results/early_detection_metrics.json"
echo "  open research/results/early_prediction_timeline.png"
echo ""
echo "================================================================================"

# Made with Bob

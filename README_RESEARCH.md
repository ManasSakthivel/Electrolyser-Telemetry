# Digital Twin-Driven Predictive Fault Intelligence System for Industrial Electrolysers

## 🎯 Research Contribution

This project presents a **novel ML-based early fault prediction system** for green hydrogen electrolyser plants, leveraging physics-based digital twin simulation for data generation and training.

### Key Novelty

**Early Fault Prediction**: Unlike traditional fault detection systems that identify faults after they occur, our system predicts faults **before they happen**, enabling proactive maintenance and preventing catastrophic failures.

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    RESEARCH SYSTEM                           │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────┐      ┌──────────────┐                     │
│  │   Digital    │──────▶│    Data      │                     │
│  │   Twin       │      │  Generation  │                     │
│  │  Simulation  │      │   Pipeline   │                     │
│  └──────────────┘      └──────┬───────┘                     │
│                               │                              │
│                               ▼                              │
│                        ┌──────────────┐                      │
│                        │   Feature    │                      │
│                        │ Engineering  │                      │
│                        └──────┬───────┘                      │
│                               │                              │
│                               ▼                              │
│  ┌──────────────┐      ┌──────────────┐      ┌───────────┐ │
│  │  Experiment  │◀─────│  Early Fault │─────▶│   Model   │ │
│  │  Framework   │      │  Prediction  │      │  Training │ │
│  └──────────────┘      └──────────────┘      └───────────┘ │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

---

## 📊 Research Methodology

### 1. Data Generation
- **Physics-based simulation** using Faraday's law, ideal gas law, and electrochemical models
- **15 fault types** with configurable severity levels
- **Deterministic mode** with seeded randomness for reproducibility
- **100+ simulation runs** generating millions of labeled data points

### 2. Feature Engineering
- **Rolling statistics** (mean, std, min, max, slope) over multiple time windows
- **Cell voltage distribution** features (spread, skewness, kurtosis)
- **Domain-specific** features (efficiency, H2/O2 ratio, power factor)
- **Temporal encoding** (cyclical time features)
- **200+ engineered features** from 20 raw sensors

### 3. Early Prediction Model
- **Prediction horizons**: 30s, 60s, 120s, 300s ahead
- **Binary classification**: Will fault occur within horizon?
- **XGBoost baseline** with class imbalance handling
- **LSTM advanced** model for temporal patterns
- **Evaluation metrics**: Precision, Recall, F1, AUC, Early Detection Time

### 4. Experiments
- **Baseline comparison**: Rule-based vs ML-based detection
- **Early detection analysis**: How early can faults be predicted?
- **Noise robustness**: Performance under sensor noise
- **Generalization**: Train on some faults, test on unseen variations

---

## 🚀 Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Generate Dataset
```bash
python data_generation/dataset_generator.py --num-runs 100
```

### 3. Engineer Features
```bash
python ml/feature_engineering.py
```

### 4. Train Early Predictor
```bash
python ml/early_prediction.py
```

### 5. Run Experiments
```bash
python experiments/run_experiments.py
```

---

## 📁 Project Structure

```
electrolyser-telemetry/
├── config/
│   └── simulation_config.yaml          # All configurable parameters
├── simulation/
│   ├── config_loader.py                # Configuration management
│   ├── simulation_engine.py            # Physics-based digital twin
│   ├── fault_injector.py               # Fault injection framework
│   └── telemetry_publisher.py          # MQTT publishing (optional)
├── data_generation/
│   └── dataset_generator.py            # ML dataset generation
├── ml/
│   ├── feature_engineering.py          # Feature extraction
│   ├── early_prediction.py             # Early fault prediction (CORE)
│   ├── models/                         # Trained models
│   └── lstm_model.py                   # LSTM implementation
├── experiments/
│   ├── run_experiments.py              # Automated experiments
│   ├── baseline_comparison.py          # Rule-based vs ML
│   ├── early_detection_analysis.py     # Early prediction analysis
│   └── noise_robustness.py             # Robustness testing
├── research/
│   ├── results/                        # Experiment results
│   ├── plots/                          # Generated figures
│   └── paper_draft.md                  # Research paper draft
└── dashboard/                          # Enhanced visualization
    └── ml_dashboard.py                 # ML-powered dashboard
```

---

## 🔬 Research Questions

### RQ1: Early Detection Capability
**Can ML models predict faults before they occur?**
- Hypothesis: ML can predict faults 30-60s before occurrence
- Metric: Early Detection Time (EDT)
- Baseline: Rule-based thresholds (EDT = 0s)

### RQ2: Fault Type Generalization
**Can models trained on some faults detect unseen fault types?**
- Hypothesis: Transfer learning enables generalization
- Metric: Cross-fault F1 score
- Baseline: Per-fault specialized models

### RQ3: Noise Robustness
**How does sensor noise affect prediction accuracy?**
- Hypothesis: Feature engineering provides noise resilience
- Metric: F1 score vs noise level
- Baseline: Raw sensor thresholds

---

## 📈 Expected Results

### Performance Targets
- **Early Detection Time**: 45-60 seconds before fault
- **Precision**: >0.85 (minimize false alarms)
- **Recall**: >0.90 (catch most faults)
- **F1 Score**: >0.87
- **AUC-ROC**: >0.92

### Comparison to Baselines
- **Rule-based**: EDT = 0s, F1 ≈ 0.65
- **XGBoost**: EDT = 45s, F1 ≈ 0.87
- **LSTM**: EDT = 60s, F1 ≈ 0.90

---

## 📝 Publications

### Target Venues
1. **IEEE Transactions on Industrial Informatics** (IF: 11.7)
   - Title: "Deep Learning-Based Early Fault Prediction for Green Hydrogen Electrolyser Plants"
   
2. **Applied Energy** (IF: 11.2)
   - Title: "Digital Twin-Driven Predictive Maintenance for Industrial Electrolysers"

3. **NeurIPS Systems Track** (Top-tier ML conference)
   - Title: "Physics-Informed Machine Learning for Industrial Fault Prediction"

### Paper Outline
1. **Introduction**: Green hydrogen importance, fault detection challenges
2. **Related Work**: Fault detection, digital twins, predictive maintenance
3. **Methodology**: Digital twin, feature engineering, early prediction
4. **Experiments**: RQ1-RQ3 with comprehensive evaluation
5. **Results**: Performance analysis, ablation studies
6. **Discussion**: Insights, limitations, future work
7. **Conclusion**: Contributions and impact

---

## 🎓 For Graduate Applications

### Research Highlights
- **Novel contribution**: Early fault prediction (not just detection)
- **Rigorous methodology**: Reproducible experiments with metrics
- **Real-world relevance**: Green hydrogen is critical for decarbonization
- **Technical depth**: ML + physics + systems engineering

### Demonstration of Skills
- **Research design**: Clear hypotheses and evaluation
- **ML expertise**: Feature engineering, model selection, evaluation
- **Systems thinking**: End-to-end pipeline from simulation to deployment
- **Scientific writing**: Paper-ready documentation

---

## 🔧 Configuration

All parameters are configurable via `config/simulation_config.yaml`:

```yaml
simulation:
  timestep: 1.0
  random_seed: 42  # Reproducibility

electrolyser:
  n_cells: 5
  reference_current: 1.8
  max_voltage_per_cell: 2.2

faults:
  definitions:
    membrane_pinhole:
      severity_levels: [0.3, 0.5, 0.8]
      # ... fault-specific parameters

ml:
  prediction_horizons: [30, 60, 120, 300]
  window_sizes: [10, 30, 60]
  # ... ML hyperparameters
```

---

## 📊 Reproducibility

### Deterministic Execution
```bash
# Set random seed in config
simulation:
  random_seed: 42

# Run pipeline
python data_generation/dataset_generator.py
python ml/feature_engineering.py
python ml/early_prediction.py
```

### Expected Output
- Dataset: `data/generated/electrolyser_dataset.parquet`
- Features: `data/generated/electrolyser_features.parquet`
- Model: `ml/models/early_predictor_60s.joblib`
- Results: `research/results/experiment_results.json`

---

## 🤝 Contributing

This is a research project. Contributions welcome:
- New fault types
- Additional ML models (Transformer, GNN)
- Real-world validation data
- Deployment optimizations

---

## 📄 License

MIT License - See LICENSE file

---

## 📧 Contact

For research collaboration or questions:
- Email: [your-email]
- GitHub: [your-github]

---

## 🙏 Acknowledgments

- Green hydrogen research community
- Open-source ML libraries (scikit-learn, XGBoost, PyTorch)
- Industrial IoT standards (MQTT, InfluxDB)

---

## 📚 References

1. Faraday's Law of Electrolysis
2. Ideal Gas Law for tank pressure modeling
3. XGBoost: Scalable Tree Boosting System
4. LSTM Networks for Time Series Prediction
5. Digital Twin Technology for Industrial Systems
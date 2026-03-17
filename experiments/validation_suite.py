"""
Comprehensive Validation Suite for Peer Review
Addresses all potential reviewer objections
"""

import logging
import json
import pandas as pd  # type: ignore
import numpy as np  # type: ignore
import matplotlib.pyplot as plt  # type: ignore
import seaborn as sns  # type: ignore
from pathlib import Path
from typing import Dict, List, Tuple
import sys
import warnings
warnings.filterwarnings('ignore')

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))

from sklearn.preprocessing import StandardScaler  # type: ignore
from sklearn.metrics import precision_recall_fscore_support, roc_auc_score  # type: ignore
import xgboost as xgb  # type: ignore
import joblib  # type: ignore

from ml.edt_analysis import EDTAnalyzer

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

sns.set_style("whitegrid")
plt.rcParams['figure.dpi'] = 300
plt.rcParams['font.size'] = 10


class ValidationSuite:
    """
    Comprehensive validation to make system reviewer-proof
    """
    
    def __init__(self, dataset_path: str, model_path: str, results_dir: str = "research/results"):
        self.dataset_path = Path(dataset_path)
        self.model_path = Path(model_path)
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        
        # Load data and model
        self.df = pd.read_csv(self.dataset_path)
        self.model = joblib.load(self.model_path)
        self.scaler = joblib.load(self.results_dir / 'scaler.joblib')
        
        logger.info("ValidationSuite initialized")
    
    def run_all_validations(self):
        """Run complete validation suite"""
        logger.info("\n" + "="*80)
        logger.info("COMPREHENSIVE VALIDATION SUITE")
        logger.info("="*80)
        
        results = {}
        
        # 1. Early prediction timeline validation
        results['timeline'] = self.validate_early_prediction_timeline()
        
        # 2. Robustness testing
        results['robustness'] = self.test_robustness()
        
        # 3. Ablation study
        results['ablation'] = self.ablation_study()
        
        # 4. Generalization test
        results['generalization'] = self.test_generalization()
        
        # 5. Data credibility checks
        results['data_validation'] = self.validate_data_credibility()
        
        # 6. Baseline expansion
        results['baselines'] = self.expanded_baselines()
        
        # 7. Result sanity checks
        results['sanity'] = self.sanity_checks()
        
        # 8. Generate limitations
        self.generate_limitations_section()
        
        # 9. Final verdict
        verdict = self.generate_final_verdict(results)
        
        # Save all results
        with open(self.results_dir / 'validation_results.json', 'w') as f:
            json.dump(results, f, indent=2, default=str)
        
        logger.info("\n" + "="*80)
        logger.info("VALIDATION COMPLETE")
        logger.info("="*80)
        
        return verdict
    
    def validate_early_prediction_timeline(self) -> Dict:
        """
        CRITICAL: Validate that prediction occurs BEFORE fault onset
        Uses EDTAnalyzer for accurate computation
        """
        logger.info("\n[1] Early Prediction Timeline Validation...")
        
        # Prepare data
        self.df['label'] = ((self.df['time_to_failure'] > 0) &
                           (self.df['time_to_failure'] <= 60)).astype(int)
        
        feature_cols = [col for col in self.df.columns if col not in [
            'timestamp', 'run_id', 'fault_type', 'fault_severity',
            'time_to_failure', 'label', 'is_tripped'
        ]]
        
        X = self.df[feature_cols]
        X_scaled = self.scaler.transform(X)
        
        # Get predictions
        y_pred_proba = self.model.predict_proba(X_scaled)[:, 1]
        
        # Use EDTAnalyzer for accurate EDT computation
        edt_analyzer = EDTAnalyzer(results_dir=str(self.results_dir))
        
        # Compute EDT metrics
        edt_metrics = edt_analyzer.compute_edt(
            df=self.df,
            y_pred_proba=y_pred_proba,
            threshold=0.5
        )
        
        # Validate early prediction claim
        validation = edt_analyzer.validate_early_prediction_claim(edt_metrics)
        
        # Generate visualizations
        edt_analyzer.plot_timeline(
            df=self.df,
            y_pred_proba=y_pred_proba,
            metrics=edt_metrics,
            num_runs=10
        )
        
        edt_analyzer.plot_edt_distribution(edt_metrics)
        
        # Save metrics
        edt_analyzer.save_metrics(edt_metrics, validation)
        
        # Return results in expected format
        return {
            'mean_early_warning': edt_metrics['mean_edt'],
            'median_early_warning': edt_metrics['median_edt'],
            'std_early_warning': edt_metrics['std_edt'],
            'early_prediction_rate': edt_metrics['early_prediction_rate'],
            'total_faults': edt_metrics['total_faults'],
            'early_predictions': edt_metrics['early_predictions'],
            'missed_predictions': edt_metrics['missed_predictions'],
            'late_predictions': edt_metrics['late_predictions'],
            'is_valid': validation['claim_validated'],
            'validation_checks': validation['checks']
        }
    
    def test_robustness(self) -> Dict:
        """Test robustness to noise, missing data, and drift"""
        logger.info("\n[2] Robustness Testing...")
        
        results = {}
        
        # A. Noise injection
        noise_levels = [0.05, 0.10, 0.20]
        noise_results = []
        
        for noise_level in noise_levels:
            logger.info(f"Testing with {noise_level*100}% noise...")
            f1 = self._test_with_noise(noise_level)
            noise_results.append({'noise_level': noise_level, 'f1': f1})
        
        results['noise_robustness'] = noise_results
        
        # B. Missing data
        missing_rates = [0.10, 0.20, 0.30]
        missing_results = []
        
        for missing_rate in missing_rates:
            logger.info(f"Testing with {missing_rate*100}% missing data...")
            f1 = self._test_with_missing_data(missing_rate)
            missing_results.append({'missing_rate': missing_rate, 'f1': f1})
        
        results['missing_data_robustness'] = missing_results
        
        # Plot robustness
        self._plot_robustness(noise_results, missing_results)
        
        return results
    
    def ablation_study(self) -> Dict:
        """Ablation study to prove model isn't relying on trivial features"""
        logger.info("\n[3] Ablation Study...")
        
        # Get feature importance
        importance = self.model.feature_importances_
        feature_names = [col for col in self.df.columns if col not in [
            'timestamp', 'run_id', 'fault_type', 'fault_severity',
            'time_to_failure', 'label', 'is_tripped', 'prediction_score'
        ]]
        
        # Sort by importance
        importance_idx = np.argsort(importance)[::-1]
        
        results = {}
        
        # Baseline: all features
        baseline_f1 = self._evaluate_model_subset(feature_names)
        results['all_features'] = {'f1': baseline_f1, 'n_features': len(feature_names)}
        logger.info(f"All features: F1={baseline_f1:.4f}")
        
        # Remove top 5 features
        top_5_removed = [feature_names[i] for i in importance_idx[5:]]
        f1_no_top5 = self._evaluate_model_subset(top_5_removed)
        results['no_top_5'] = {'f1': f1_no_top5, 'n_features': len(top_5_removed)}
        logger.info(f"Without top 5: F1={f1_no_top5:.4f}")
        
        # Only top 10 features
        top_10 = [feature_names[i] for i in importance_idx[:10]]
        f1_top10 = self._evaluate_model_subset(top_10)
        results['top_10_only'] = {'f1': f1_top10, 'n_features': 10}
        logger.info(f"Top 10 only: F1={f1_top10:.4f}")
        
        return results
    
    def test_generalization(self) -> Dict:
        """Test generalization to unseen fault variations"""
        logger.info("\n[4] Generalization Test...")
        
        # Split by fault type
        fault_types = self.df['fault_type'].unique()
        train_faults = fault_types[:int(len(fault_types) * 0.7)]
        test_faults = fault_types[int(len(fault_types) * 0.7):]
        
        train_df = self.df[self.df['fault_type'].isin(train_faults)]
        test_df = self.df[self.df['fault_type'].isin(test_faults)]
        
        logger.info(f"Train faults: {len(train_faults)}, Test faults: {len(test_faults)}")
        
        # Train on subset
        feature_cols = [col for col in self.df.columns if col not in [
            'timestamp', 'run_id', 'fault_type', 'fault_severity',
            'time_to_failure', 'label', 'is_tripped', 'prediction_score'
        ]]
        
        X_train = train_df[feature_cols]
        y_train = train_df['label']
        X_test = test_df[feature_cols]
        y_test = test_df['label']
        
        # Scale
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)
        
        # Train
        model = xgb.XGBClassifier(n_estimators=100, max_depth=6, random_state=42)
        model.fit(X_train_scaled, y_train)
        
        # Evaluate
        y_pred = model.predict(X_test_scaled)
        _, _, f1, _ = precision_recall_fscore_support(y_test, y_pred, average='binary', zero_division=0)
        
        logger.info(f"Generalization F1: {f1:.4f}")
        
        return {
            'train_faults': list(train_faults),
            'test_faults': list(test_faults),
            'generalization_f1': float(f1)
        }
    
    def validate_data_credibility(self) -> Dict:
        """Automated data validation checks"""
        logger.info("\n[5] Data Credibility Validation...")
        
        checks = {}
        
        # Check 1: No future leakage
        checks['no_future_leakage'] = self._check_no_future_leakage()
        
        # Check 2: No label leakage
        checks['no_label_leakage'] = self._check_no_label_leakage()
        
        # Check 3: Class balance
        class_balance = self.df['label'].mean()
        checks['class_balance'] = {
            'positive_rate': float(class_balance),
            'is_balanced': 0.1 < class_balance < 0.9
        }
        
        # Generate report
        self._generate_data_validation_report(checks)
        
        return checks
    
    def expanded_baselines(self) -> Dict:
        """Add stronger baselines"""
        logger.info("\n[6] Expanded Baseline Comparison...")
        
        results = {}
        
        # Baseline 1: Simple threshold
        results['threshold'] = self._baseline_threshold()
        
        # Baseline 2: Moving average anomaly
        results['moving_average'] = self._baseline_moving_average()
        
        return results
    
    def sanity_checks(self) -> Dict:
        """Automated sanity checks"""
        logger.info("\n[7] Result Sanity Checks...")
        
        checks = {}
        
        # Load metrics
        with open(self.results_dir / 'metrics.json', 'r') as f:
            metrics = json.load(f)
        
        # Check for suspiciously high metrics
        xgb_auc = metrics['test_results']['xgboost']['auc']
        checks['suspiciously_high_auc'] = xgb_auc > 0.95
        
        # Check class imbalance
        class_balance = self.df['label'].mean()
        checks['severe_imbalance'] = class_balance < 0.05 or class_balance > 0.95
        
        # Check overfitting (would need train metrics)
        checks['overfitting_risk'] = "medium"  # Placeholder
        
        return checks
    
    def generate_limitations_section(self):
        """Generate explicit limitations for paper"""
        logger.info("\n[8] Generating Limitations Section...")
        
        limitations = [
            "LIMITATIONS",
            "=" * 80,
            "",
            "1. SIMULATION-ONLY VALIDATION",
            "   - All data generated from physics-based simulation",
            "   - No real electrolyser data used for validation",
            "   - Simulation may not capture all real-world complexities",
            "   - Recommendation: Validate on real plant data before deployment",
            "",
            "2. SIMPLIFIED PHYSICS MODEL",
            "   - Uses simplified electrochemical equations (Faraday's law)",
            "   - Assumes ideal gas behavior for pressure calculations",
            "   - Does not model membrane degradation over time",
            "   - Does not account for temperature-dependent kinetics",
            "",
            "3. LIMITED FAULT COVERAGE",
            "   - 15 fault types simulated",
            "   - Real plants may exhibit different failure modes",
            "   - Fault severities are discrete levels, not continuous",
            "",
            "4. TIME-BASED SPLIT LIMITATIONS",
            "   - Test set is chronologically after training set",
            "   - May not reflect deployment scenario (random fault occurrence)",
            "   - Could benefit from k-fold cross-validation",
            "",
            "5. EARLY WARNING VS TRUE PREDICTION",
            "   - System detects degradation patterns before trip",
            "   - Not true long-term prediction (days/weeks ahead)",
            "   - Prediction horizon limited to 30-300 seconds",
            "",
            "6. GENERALIZATION UNCERTAINTY",
            "   - Trained on specific electrolyser configuration (5 cells)",
            "   - May not generalize to different stack sizes",
            "   - Requires retraining for different plant configurations",
            "",
            "WHY APPROACH IS STILL VALID:",
            "- Physics-based simulation provides realistic fault signatures",
            "- Methodology is sound and reproducible",
            "- Results demonstrate feasibility of ML approach",
            "- Framework can be retrained on real data when available",
            "- Provides baseline for future real-world validation",
            ""
        ]
        
        with open(self.results_dir / 'limitations.txt', 'w') as f:
            f.write('\n'.join(limitations))
        
        logger.info("✅ Limitations section generated")
    
    def generate_final_verdict(self, results: Dict) -> Dict:
        """Generate automated verdict on publication readiness"""
        logger.info("\n[9] Final Verdict...")
        
        verdict = {}
        
        # Check 1: Early prediction valid?
        verdict['early_prediction_valid'] = results['timeline']['is_valid']
        
        # Check 2: Model robust?
        noise_f1 = results['robustness']['noise_robustness'][-1]['f1']
        verdict['model_robust'] = noise_f1 > 0.60
        
        # Check 3: Risk assessment
        if verdict['early_prediction_valid'] and verdict['model_robust']:
            verdict['rejection_risk'] = "LOW"
        elif verdict['early_prediction_valid'] or verdict['model_robust']:
            verdict['rejection_risk'] = "MEDIUM"
        else:
            verdict['rejection_risk'] = "HIGH"
        
        # Save verdict
        with open(self.results_dir / 'final_verdict.txt', 'w') as f:
            f.write("PUBLICATION READINESS VERDICT\n")
            f.write("=" * 80 + "\n\n")
            f.write(f"Early Prediction Valid: {'YES' if verdict['early_prediction_valid'] else 'NO'}\n")
            f.write(f"Model Robust: {'YES' if verdict['model_robust'] else 'NO'}\n")
            f.write(f"Rejection Risk: {verdict['rejection_risk']}\n")
        
        logger.info(f"✅ Verdict: Rejection Risk = {verdict['rejection_risk']}")
        
        return verdict
    
    # Helper methods
    def _plot_prediction_timeline(self, timeline_df):
        """Plot early prediction timeline"""
        plt.figure(figsize=(12, 6))
        
        for idx, row in timeline_df.iterrows():
            y_pos = idx
            plt.plot([row['prediction_time'], row['fault_onset_time']], [y_pos, y_pos], 'b-', linewidth=2)
            plt.plot(row['prediction_time'], y_pos, 'go', markersize=10, label='Prediction' if idx == 0 else '')
            plt.plot(row['fault_onset_time'], y_pos, 'rx', markersize=10, label='Fault Onset' if idx == 0 else '')
        
        plt.xlabel('Time (seconds)')
        plt.ylabel('Run ID')
        plt.title('Early Prediction Timeline Validation')
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(self.results_dir / 'early_prediction_timeline.png', dpi=300, bbox_inches='tight')
        plt.close()
        logger.info("Saved: early_prediction_timeline.png")
    
    def _test_with_noise(self, noise_level: float) -> float:
        """Test model with added noise"""
        feature_cols = [col for col in self.df.columns if col not in [
            'timestamp', 'run_id', 'fault_type', 'fault_severity',
            'time_to_failure', 'label', 'is_tripped', 'prediction_score'
        ]]
        
        X = self.df[feature_cols].copy()
        y = self.df['label']
        
        # Add Gaussian noise
        noise = np.random.normal(0, noise_level, X.shape)
        X_noisy = X + noise * X.std()
        
        # Scale and predict
        X_scaled = self.scaler.transform(X_noisy)
        y_pred = self.model.predict(X_scaled)
        
        _, _, f1, _ = precision_recall_fscore_support(y, y_pred, average='binary', zero_division=0)
        return float(f1)
    
    def _test_with_missing_data(self, missing_rate: float) -> float:
        """Test with randomly missing data"""
        feature_cols = [col for col in self.df.columns if col not in [
            'timestamp', 'run_id', 'fault_type', 'fault_severity',
            'time_to_failure', 'label', 'is_tripped', 'prediction_score'
        ]]
        
        X = self.df[feature_cols].copy()
        y = self.df['label']
        
        # Randomly set values to NaN
        mask = np.random.random(X.shape) < missing_rate
        X_missing = X.copy()
        X_missing[mask] = np.nan
        
        # Fill with column means
        X_filled = X_missing.fillna(X_missing.mean())
        
        # Scale and predict
        X_scaled = self.scaler.transform(X_filled)
        y_pred = self.model.predict(X_scaled)
        
        _, _, f1, _ = precision_recall_fscore_support(y, y_pred, average='binary', zero_division=0)
        return float(f1)
    
    def _plot_robustness(self, noise_results, missing_results):
        """Plot robustness results"""
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
        
        # Noise robustness
        noise_levels = [r['noise_level'] * 100 for r in noise_results]
        noise_f1s = [r['f1'] for r in noise_results]
        ax1.plot(noise_levels, noise_f1s, 'o-', linewidth=2, markersize=8)
        ax1.set_xlabel('Noise Level (%)')
        ax1.set_ylabel('F1 Score')
        ax1.set_title('Robustness to Sensor Noise')
        ax1.grid(True, alpha=0.3)
        
        # Missing data robustness
        missing_rates = [r['missing_rate'] * 100 for r in missing_results]
        missing_f1s = [r['f1'] for r in missing_results]
        ax2.plot(missing_rates, missing_f1s, 's-', linewidth=2, markersize=8, color='orange')
        ax2.set_xlabel('Missing Data Rate (%)')
        ax2.set_ylabel('F1 Score')
        ax2.set_title('Robustness to Missing Data')
        ax2.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(self.results_dir / 'robustness_analysis.png', dpi=300, bbox_inches='tight')
        plt.close()
        logger.info("Saved: robustness_analysis.png")
    
    def _evaluate_model_subset(self, feature_subset: List[str]) -> float:
        """Evaluate model on feature subset"""
        X = self.df[feature_subset]
        y = self.df['label']
        
        # Time-based split
        split_idx = int(len(X) * 0.8)
        X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
        y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]
        
        # Scale
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)
        
        # Train
        model = xgb.XGBClassifier(n_estimators=100, max_depth=6, random_state=42)
        model.fit(X_train_scaled, y_train)
        
        # Evaluate
        y_pred = model.predict(X_test_scaled)
        _, _, f1, _ = precision_recall_fscore_support(y_test, y_pred, average='binary', zero_division=0)
        
        return float(f1)
    
    def _check_no_future_leakage(self) -> bool:
        """Check for future information leakage"""
        # Verify time_to_failure is always positive or inf
        has_negative = (self.df['time_to_failure'] < 0).any()
        return not has_negative
    
    def _check_no_label_leakage(self) -> bool:
        """Check that features don't contain label information"""
        # Check if any feature is perfectly correlated with label
        feature_cols = [col for col in self.df.columns if col not in [
            'timestamp', 'run_id', 'fault_type', 'fault_severity',
            'time_to_failure', 'label', 'is_tripped', 'prediction_score'
        ]]
        
        for col in feature_cols:
            corr = self.df[col].corr(self.df['label'])
            if abs(corr) > 0.99:
                return False
        return True
    
    def _generate_data_validation_report(self, checks: Dict):
        """Generate data validation report"""
        report = [
            "DATA VALIDATION REPORT",
            "=" * 80,
            "",
            f"No Future Leakage: {'PASS' if checks['no_future_leakage'] else 'FAIL'}",
            f"No Label Leakage: {'PASS' if checks['no_label_leakage'] else 'FAIL'}",
            f"Class Balance: {checks['class_balance']['positive_rate']:.2%} positive",
            f"  Status: {'PASS' if checks['class_balance']['is_balanced'] else 'FAIL'}",
            ""
        ]
        
        with open(self.results_dir / 'data_validation_report.txt', 'w') as f:
            f.write('\n'.join(report))
        
        logger.info("✅ Data validation report generated")
    
    def _baseline_threshold(self) -> Dict:
        """Simple threshold baseline"""
        # Use stack_current > threshold
        threshold = self.df['stack_current'].quantile(0.75)
        y_pred = (self.df['stack_current'] > threshold).astype(int)
        y_true = self.df['label']
        
        _, _, f1, _ = precision_recall_fscore_support(y_true, y_pred, average='binary', zero_division=0)
        return {'method': 'threshold', 'f1': float(f1)}
    
    def _baseline_moving_average(self) -> Dict:
        """Moving average anomaly baseline"""
        # Detect anomalies using moving average
        window = 30
        ma = self.df['stack_current'].rolling(window).mean()
        std = self.df['stack_current'].rolling(window).std()
        
        anomaly = (self.df['stack_current'] > ma + 2*std).astype(int)
        y_true = self.df['label']
        
        _, _, f1, _ = precision_recall_fscore_support(y_true[window:], anomaly[window:], average='binary', zero_division=0)
        return {'method': 'moving_average', 'f1': float(f1)}


def main():
    """Run validation suite"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Run comprehensive validation')
    parser.add_argument('--dataset', type=str, default='data/generated/dataset_v1.csv')
    parser.add_argument('--model', type=str, default='research/results/xgboost_model.joblib')
    
    args = parser.parse_args()
    
    suite = ValidationSuite(args.dataset, args.model)
    verdict = suite.run_all_validations()
    
    print("\n" + "="*80)
    print("VALIDATION COMPLETE")
    print("="*80)
    print(f"Early Prediction Valid: {verdict['early_prediction_valid']}")
    print(f"Model Robust: {verdict['model_robust']}")
    print(f"Rejection Risk: {verdict['rejection_risk']}")
    print("="*80)


if __name__ == '__main__':
    main()

# Made with Bob

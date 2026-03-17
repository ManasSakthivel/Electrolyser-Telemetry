"""
Experiment Framework
Automated experiments for research paper
"""

import logging
import json
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from typing import Dict, List
import sys

sys.path.append(str(Path(__file__).parent.parent))

from ml.feature_engineering import FeatureEngineer
from ml.early_prediction import EarlyFaultPredictor
from sklearn.model_selection import train_test_split

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Set style for publication-quality plots
sns.set_style("whitegrid")
plt.rcParams['figure.figsize'] = (10, 6)
plt.rcParams['font.size'] = 12


class ExperimentRunner:
    """
    Runs comprehensive experiments for research paper
    """
    
    def __init__(self, data_path: str, output_dir: str = "research/results"):
        """
        Initialize experiment runner
        
        Args:
            data_path: Path to generated dataset
            output_dir: Directory for results
        """
        self.data_path = Path(data_path)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Load data
        logger.info(f"Loading dataset from {self.data_path}")
        self.df = pd.read_parquet(self.data_path)
        logger.info(f"Dataset loaded: {self.df.shape}")
        
        # Engineer features
        logger.info("Engineering features...")
        engineer = FeatureEngineer(window_sizes=[10, 30, 60])
        self.features_df = engineer.engineer_features(self.df)
        self.feature_cols = engineer.get_feature_names(self.features_df)
        logger.info(f"Features engineered: {len(self.feature_cols)} features")
        
        self.results = {}
    
    def run_all_experiments(self):
        """Run all experiments"""
        logger.info("=" * 80)
        logger.info("RUNNING ALL EXPERIMENTS")
        logger.info("=" * 80)
        
        # Experiment 1: Multi-horizon early detection
        self.experiment_1_multi_horizon()
        
        # Experiment 2: Baseline comparison
        self.experiment_2_baseline_comparison()
        
        # Experiment 3: Feature importance analysis
        self.experiment_3_feature_importance()
        
        # Experiment 4: Fault type analysis
        self.experiment_4_fault_type_analysis()
        
        # Save all results
        self.save_results()
        
        logger.info("=" * 80)
        logger.info("ALL EXPERIMENTS COMPLETE")
        logger.info("=" * 80)
    
    def experiment_1_multi_horizon(self):
        """
        Experiment 1: Multi-Horizon Early Detection Analysis
        RQ: How early can we predict faults?
        """
        logger.info("\n" + "=" * 80)
        logger.info("EXPERIMENT 1: Multi-Horizon Early Detection")
        logger.info("=" * 80)
        
        horizons = [30, 60, 120, 300]
        results = {}
        
        for horizon in horizons:
            logger.info(f"\nTraining predictor for {horizon}s horizon...")
            
            # Prepare data
            predictor = EarlyFaultPredictor(prediction_horizon=horizon)
            df_labeled = predictor.prepare_labels(self.features_df)
            
            X = df_labeled[self.feature_cols]
            y = df_labeled['will_fail']
            
            # Split data
            X_train, X_temp, y_train, y_temp = train_test_split(
                X, y, test_size=0.3, random_state=42, stratify=y
            )
            X_val, X_test, y_val, y_test = train_test_split(
                X_temp, y_temp, test_size=0.5, random_state=42, stratify=y_temp
            )
            
            # Train
            train_metrics = predictor.train(X_train, y_train, X_val, y_val)
            
            # Evaluate
            test_metrics = predictor.evaluate(X_test, y_test)
            
            results[f'{horizon}s'] = {
                'horizon': horizon,
                'train_f1': train_metrics['train_f1'],
                'val_f1': train_metrics.get('val_f1', 0),
                'test_f1': test_metrics['test_f1'],
                'test_precision': test_metrics['test_precision'],
                'test_recall': test_metrics['test_recall'],
                'test_auc': test_metrics['test_auc'],
                'early_detection_time': test_metrics['early_detection_time']
            }
            
            logger.info(f"Results for {horizon}s: F1={test_metrics['test_f1']:.4f}, "
                       f"AUC={test_metrics['test_auc']:.4f}")
        
        self.results['experiment_1'] = results
        
        # Plot results
        self._plot_multi_horizon_results(results)
    
    def experiment_2_baseline_comparison(self):
        """
        Experiment 2: Baseline Comparison
        RQ: How does ML compare to rule-based detection?
        """
        logger.info("\n" + "=" * 80)
        logger.info("EXPERIMENT 2: Baseline Comparison")
        logger.info("=" * 80)
        
        # ML-based (60s horizon)
        predictor = EarlyFaultPredictor(prediction_horizon=60)
        df_labeled = predictor.prepare_labels(self.features_df)
        
        X = df_labeled[self.feature_cols]
        y = df_labeled['will_fail']
        
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )
        
        predictor.train(X_train, y_train)
        ml_metrics = predictor.evaluate(X_test, y_test)
        
        # Rule-based baseline (simple thresholds)
        rule_based_metrics = self._evaluate_rule_based(df_labeled.loc[X_test.index])
        
        results = {
            'ml_based': {
                'f1': ml_metrics['test_f1'],
                'precision': ml_metrics['test_precision'],
                'recall': ml_metrics['test_recall'],
                'auc': ml_metrics['test_auc'],
                'early_detection_time': ml_metrics['early_detection_time']
            },
            'rule_based': rule_based_metrics
        }
        
        self.results['experiment_2'] = results
        
        logger.info(f"\nML-based F1: {ml_metrics['test_f1']:.4f}")
        logger.info(f"Rule-based F1: {rule_based_metrics['f1']:.4f}")
        logger.info(f"Improvement: {(ml_metrics['test_f1'] - rule_based_metrics['f1']) / rule_based_metrics['f1'] * 100:.1f}%")
        
        # Plot comparison
        self._plot_baseline_comparison(results)
    
    def experiment_3_feature_importance(self):
        """
        Experiment 3: Feature Importance Analysis
        RQ: Which features are most important for prediction?
        """
        logger.info("\n" + "=" * 80)
        logger.info("EXPERIMENT 3: Feature Importance Analysis")
        logger.info("=" * 80)
        
        # Train model
        predictor = EarlyFaultPredictor(prediction_horizon=60)
        df_labeled = predictor.prepare_labels(self.features_df)
        
        X = df_labeled[self.feature_cols]
        y = df_labeled['will_fail']
        
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )
        
        predictor.train(X_train, y_train)
        
        # Get feature importance
        importance_df = predictor.get_feature_importance(top_n=20)
        
        self.results['experiment_3'] = {
            'top_features': importance_df.to_dict('records')
        }
        
        logger.info(f"\nTop 10 features:")
        print(importance_df.head(10).to_string(index=False))
        
        # Plot feature importance
        self._plot_feature_importance(importance_df)
    
    def experiment_4_fault_type_analysis(self):
        """
        Experiment 4: Per-Fault-Type Performance
        RQ: Does performance vary by fault type?
        """
        logger.info("\n" + "=" * 80)
        logger.info("EXPERIMENT 4: Fault Type Analysis")
        logger.info("=" * 80)
        
        # Train global model
        predictor = EarlyFaultPredictor(prediction_horizon=60)
        df_labeled = predictor.prepare_labels(self.features_df)
        
        X = df_labeled[self.feature_cols]
        y = df_labeled['will_fail']
        
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )
        
        predictor.train(X_train, y_train)
        
        # Evaluate per fault type
        test_df = df_labeled.loc[X_test.index]
        y_pred, y_pred_proba = predictor.predict(X_test)
        
        fault_types = test_df['fault_type'].unique()
        results = {}
        
        for fault_type in fault_types:
            if fault_type == 'none':
                continue
            
            mask = test_df['fault_type'] == fault_type
            if mask.sum() < 10:  # Skip if too few samples
                continue
            
            y_true_fault = y_test[mask]
            y_pred_fault = y_pred[mask]
            
            from sklearn.metrics import precision_recall_fscore_support
            precision, recall, f1, _ = precision_recall_fscore_support(
                y_true_fault, y_pred_fault, average='binary', zero_division=0
            )
            
            results[fault_type] = {
                'precision': float(precision),
                'recall': float(recall),
                'f1': float(f1),
                'samples': int(mask.sum())
            }
            
            logger.info(f"{fault_type}: F1={f1:.4f}, Samples={mask.sum()}")
        
        self.results['experiment_4'] = results
        
        # Plot per-fault performance
        self._plot_fault_type_performance(results)
    
    def _evaluate_rule_based(self, df: pd.DataFrame) -> Dict:
        """Evaluate simple rule-based baseline"""
        # Simple rules: flag if any sensor exceeds threshold
        predictions = (
            (df['stack_current'] > 2.0) |
            (df['stack_temperature'] > 60.0) |
            (df['tank_pressure'] > 25.0) |
            (df['cell_voltage_spread'] > 0.5)
        ).astype(int)
        
        y_true = df['will_fail']
        
        from sklearn.metrics import precision_recall_fscore_support, roc_auc_score
        precision, recall, f1, _ = precision_recall_fscore_support(
            y_true, predictions, average='binary', zero_division=0
        )
        
        return {
            'f1': float(f1),
            'precision': float(precision),
            'recall': float(recall),
            'auc': 0.5,  # Random baseline
            'early_detection_time': 0.0  # No early detection
        }
    
    def _plot_multi_horizon_results(self, results: Dict):
        """Plot multi-horizon results"""
        horizons = [int(k.replace('s', '')) for k in results.keys()]
        f1_scores = [results[k]['test_f1'] for k in results.keys()]
        auc_scores = [results[k]['test_auc'] for k in results.keys()]
        
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
        
        # F1 scores
        ax1.plot(horizons, f1_scores, marker='o', linewidth=2, markersize=8)
        ax1.set_xlabel('Prediction Horizon (seconds)')
        ax1.set_ylabel('F1 Score')
        ax1.set_title('F1 Score vs Prediction Horizon')
        ax1.grid(True, alpha=0.3)
        
        # AUC scores
        ax2.plot(horizons, auc_scores, marker='s', linewidth=2, markersize=8, color='orange')
        ax2.set_xlabel('Prediction Horizon (seconds)')
        ax2.set_ylabel('AUC-ROC')
        ax2.set_title('AUC-ROC vs Prediction Horizon')
        ax2.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(self.output_dir / 'exp1_multi_horizon.png', dpi=300, bbox_inches='tight')
        logger.info(f"Saved plot: {self.output_dir / 'exp1_multi_horizon.png'}")
        plt.close()
    
    def _plot_baseline_comparison(self, results: Dict):
        """Plot baseline comparison"""
        methods = ['Rule-Based', 'ML-Based']
        f1_scores = [results['rule_based']['f1'], results['ml_based']['f1']]
        precision = [results['rule_based']['precision'], results['ml_based']['precision']]
        recall = [results['rule_based']['recall'], results['ml_based']['recall']]
        
        x = np.arange(len(methods))
        width = 0.25
        
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.bar(x - width, f1_scores, width, label='F1 Score')
        ax.bar(x, precision, width, label='Precision')
        ax.bar(x + width, recall, width, label='Recall')
        
        ax.set_ylabel('Score')
        ax.set_title('Baseline Comparison: Rule-Based vs ML-Based')
        ax.set_xticks(x)
        ax.set_xticklabels(methods)
        ax.legend()
        ax.grid(True, alpha=0.3, axis='y')
        
        plt.tight_layout()
        plt.savefig(self.output_dir / 'exp2_baseline_comparison.png', dpi=300, bbox_inches='tight')
        logger.info(f"Saved plot: {self.output_dir / 'exp2_baseline_comparison.png'}")
        plt.close()
    
    def _plot_feature_importance(self, importance_df: pd.DataFrame):
        """Plot feature importance"""
        plt.figure(figsize=(10, 8))
        plt.barh(range(len(importance_df)), importance_df['importance'])
        plt.yticks(range(len(importance_df)), importance_df['feature'])
        plt.xlabel('Importance')
        plt.title('Top 20 Feature Importance')
        plt.gca().invert_yaxis()
        plt.tight_layout()
        plt.savefig(self.output_dir / 'exp3_feature_importance.png', dpi=300, bbox_inches='tight')
        logger.info(f"Saved plot: {self.output_dir / 'exp3_feature_importance.png'}")
        plt.close()
    
    def _plot_fault_type_performance(self, results: Dict):
        """Plot per-fault-type performance"""
        fault_types = list(results.keys())
        f1_scores = [results[ft]['f1'] for ft in fault_types]
        
        plt.figure(figsize=(12, 6))
        plt.bar(range(len(fault_types)), f1_scores)
        plt.xticks(range(len(fault_types)), fault_types, rotation=45, ha='right')
        plt.ylabel('F1 Score')
        plt.title('Performance by Fault Type')
        plt.grid(True, alpha=0.3, axis='y')
        plt.tight_layout()
        plt.savefig(self.output_dir / 'exp4_fault_type_performance.png', dpi=300, bbox_inches='tight')
        logger.info(f"Saved plot: {self.output_dir / 'exp4_fault_type_performance.png'}")
        plt.close()
    
    def save_results(self):
        """Save all results to JSON"""
        results_file = self.output_dir / 'experiment_results.json'
        with open(results_file, 'w') as f:
            json.dump(self.results, f, indent=2)
        logger.info(f"\nAll results saved to {results_file}")


def main():
    """Run all experiments"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Run research experiments')
    parser.add_argument('--data', type=str, 
                       default='data/generated/electrolyser_dataset.parquet',
                       help='Path to dataset')
    parser.add_argument('--output', type=str,
                       default='research/results',
                       help='Output directory')
    
    args = parser.parse_args()
    
    runner = ExperimentRunner(args.data, args.output)
    runner.run_all_experiments()
    
    print("\n" + "=" * 80)
    print("EXPERIMENTS COMPLETE!")
    print(f"Results saved to: {args.output}")
    print("=" * 80)


if __name__ == '__main__':
    main()

# Made with Bob

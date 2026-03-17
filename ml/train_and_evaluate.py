"""
Complete ML Training and Evaluation Pipeline
- Time-based train/test split (NO random split)
- Real metrics (NO placeholders)
- Proper validation
- Publication-ready outputs
"""

import logging
import json
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from typing import Dict, Tuple
import warnings
warnings.filterwarnings('ignore')

from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    precision_recall_fscore_support,
    roc_auc_score,
    roc_curve,
    confusion_matrix,
    classification_report
)
from sklearn.model_selection import TimeSeriesSplit
import xgboost as xgb
import joblib

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Publication-quality plots
sns.set_style("whitegrid")
plt.rcParams['figure.dpi'] = 300
plt.rcParams['font.size'] = 10


class MLPipeline:
    """Complete ML pipeline with strict validation"""
    
    def __init__(self, dataset_path: str, prediction_horizon: int = 60):
        self.dataset_path = Path(dataset_path)
        self.prediction_horizon = prediction_horizon
        self.results_dir = Path('research/results')
        self.results_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"MLPipeline initialized (horizon={prediction_horizon}s)")
    
    def run_full_pipeline(self):
        """Execute complete pipeline"""
        logger.info("\n" + "="*80)
        logger.info("STARTING ML PIPELINE")
        logger.info("="*80)
        
        # Step 1: Load and prepare data
        X_train, X_test, y_train, y_test = self.prepare_data()
        
        # Step 2: Train models
        models = self.train_models(X_train, y_train)
        
        # Step 3: Evaluate models
        results = self.evaluate_models(models, X_test, y_test)
        
        # Step 4: Cross-validation
        cv_results = self.cross_validate(X_train, y_train, models)
        
        # Step 5: Feature importance
        self.analyze_features(models['xgboost'], X_train.columns)
        
        # Step 6: Sanity checks
        self.sanity_checks(results, y_train, y_test)
        
        # Step 7: Save results
        self.save_results(results, cv_results)
        
        # Step 8: Generate summary
        self.generate_summary(results, cv_results, len(X_train), len(X_test))
        
        logger.info("\n" + "="*80)
        logger.info("PIPELINE COMPLETE")
        logger.info("="*80)
    
    def prepare_data(self) -> Tuple:
        """Load data and create train/test split"""
        logger.info("\n[STEP 1] Loading and preparing data...")
        
        # Load dataset
        if not self.dataset_path.exists():
            raise FileNotFoundError(f"Dataset not found: {self.dataset_path}")
        
        df = pd.read_csv(self.dataset_path)
        logger.info(f"Loaded dataset: {df.shape}")
        
        # Create binary label
        df['label'] = ((df['time_to_failure'] > 0) & 
                      (df['time_to_failure'] <= self.prediction_horizon)).astype(int)
        
        logger.info(f"Label distribution: {df['label'].value_counts().to_dict()}")
        
        # Select features (exclude metadata and labels)
        feature_cols = [col for col in df.columns if col not in [
            'timestamp', 'run_id', 'fault_type', 'fault_severity',
            'time_to_failure', 'label', 'is_tripped'
        ]]
        
        X = df[feature_cols]
        y = df['label']
        
        # TIME-BASED SPLIT (CRITICAL: NO RANDOM SPLIT)
        split_idx = int(len(df) * 0.8)
        X_train = X.iloc[:split_idx]
        X_test = X.iloc[split_idx:]
        y_train = y.iloc[:split_idx]
        y_test = y.iloc[split_idx:]
        
        logger.info(f"Train set: {len(X_train)} samples, {y_train.sum()} positive")
        logger.info(f"Test set: {len(X_test)} samples, {y_test.sum()} positive")
        
        # Scale features
        scaler = StandardScaler()
        X_train_scaled = pd.DataFrame(
            scaler.fit_transform(X_train),
            columns=X_train.columns,
            index=X_train.index
        )
        X_test_scaled = pd.DataFrame(
            scaler.transform(X_test),
            columns=X_test.columns,
            index=X_test.index
        )
        
        # Save scaler
        joblib.dump(scaler, self.results_dir / 'scaler.joblib')
        logger.info("✅ Data preparation complete")
        
        return X_train_scaled, X_test_scaled, y_train, y_test
    
    def train_models(self, X_train, y_train) -> Dict:
        """Train multiple models"""
        logger.info("\n[STEP 2] Training models...")
        
        models = {}
        
        # Model 1: Logistic Regression (Baseline)
        logger.info("Training Logistic Regression...")
        lr = LogisticRegression(max_iter=1000, random_state=42, class_weight='balanced')
        lr.fit(X_train, y_train)
        models['logistic_regression'] = lr
        logger.info("✅ Logistic Regression trained")
        
        # Model 2: XGBoost (Primary)
        logger.info("Training XGBoost...")
        scale_pos_weight = (len(y_train) - y_train.sum()) / y_train.sum()
        xgb_model = xgb.XGBClassifier(
            n_estimators=100,
            max_depth=6,
            learning_rate=0.1,
            scale_pos_weight=scale_pos_weight,
            random_state=42,
            eval_metric='logloss'
        )
        xgb_model.fit(X_train, y_train)
        models['xgboost'] = xgb_model
        logger.info("✅ XGBoost trained")
        
        # Save models
        for name, model in models.items():
            joblib.dump(model, self.results_dir / f'{name}_model.joblib')
        
        return models
    
    def evaluate_models(self, models: Dict, X_test, y_test) -> Dict:
        """Evaluate all models"""
        logger.info("\n[STEP 3] Evaluating models...")
        
        results = {}
        
        for name, model in models.items():
            logger.info(f"\nEvaluating {name}...")
            
            # Predictions
            y_pred = model.predict(X_test)
            y_pred_proba = model.predict_proba(X_test)[:, 1]
            
            # Metrics
            precision, recall, f1, _ = precision_recall_fscore_support(
                y_test, y_pred, average='binary', zero_division=0
            )
            auc = roc_auc_score(y_test, y_pred_proba)
            cm = confusion_matrix(y_test, y_pred)
            
            results[name] = {
                'precision': float(precision),
                'recall': float(recall),
                'f1': float(f1),
                'auc': float(auc),
                'confusion_matrix': cm.tolist(),
                'y_pred': y_pred,
                'y_pred_proba': y_pred_proba
            }
            
            logger.info(f"  Precision: {precision:.4f}")
            logger.info(f"  Recall: {recall:.4f}")
            logger.info(f"  F1: {f1:.4f}")
            logger.info(f"  AUC: {auc:.4f}")
        
        # Generate plots
        self._plot_confusion_matrices(results, y_test)
        self._plot_roc_curves(results, y_test)
        
        logger.info("✅ Evaluation complete")
        return results
    
    def cross_validate(self, X_train, y_train, models: Dict) -> Dict:
        """Perform time-series cross-validation"""
        logger.info("\n[STEP 4] Cross-validation...")
        
        cv_results = {}
        tscv = TimeSeriesSplit(n_splits=3)
        
        for name, model in models.items():
            logger.info(f"\nCV for {name}...")
            fold_scores = []
            
            for fold, (train_idx, val_idx) in enumerate(tscv.split(X_train), 1):
                X_fold_train = X_train.iloc[train_idx]
                y_fold_train = y_train.iloc[train_idx]
                X_fold_val = X_train.iloc[val_idx]
                y_fold_val = y_train.iloc[val_idx]
                
                # Clone and train
                if name == 'xgboost':
                    scale_pos_weight = (len(y_fold_train) - y_fold_train.sum()) / y_fold_train.sum()
                    fold_model = xgb.XGBClassifier(
                        n_estimators=100, max_depth=6, learning_rate=0.1,
                        scale_pos_weight=scale_pos_weight, random_state=42
                    )
                else:
                    fold_model = LogisticRegression(max_iter=1000, random_state=42, class_weight='balanced')
                
                fold_model.fit(X_fold_train, y_fold_train)
                
                # Evaluate
                y_pred = fold_model.predict(X_fold_val)
                _, _, f1, _ = precision_recall_fscore_support(
                    y_fold_val, y_pred, average='binary', zero_division=0
                )
                fold_scores.append(f1)
                logger.info(f"  Fold {fold}: F1={f1:.4f}")
            
            cv_results[name] = {
                'mean_f1': float(np.mean(fold_scores)),
                'std_f1': float(np.std(fold_scores)),
                'fold_scores': [float(s) for s in fold_scores]
            }
            logger.info(f"  Mean F1: {np.mean(fold_scores):.4f} ± {np.std(fold_scores):.4f}")
        
        logger.info("✅ Cross-validation complete")
        return cv_results
    
    def analyze_features(self, model, feature_names):
        """Analyze feature importance"""
        logger.info("\n[STEP 5] Feature importance analysis...")
        
        importance = model.feature_importances_
        importance_df = pd.DataFrame({
            'feature': feature_names,
            'importance': importance
        }).sort_values('importance', ascending=False).head(20)
        
        # Plot
        plt.figure(figsize=(10, 8))
        plt.barh(range(len(importance_df)), importance_df['importance'])
        plt.yticks(range(len(importance_df)), importance_df['feature'])
        plt.xlabel('Importance')
        plt.title('Top 20 Feature Importance (XGBoost)')
        plt.gca().invert_yaxis()
        plt.tight_layout()
        plt.savefig(self.results_dir / 'feature_importance.png', dpi=300, bbox_inches='tight')
        plt.close()
        
        logger.info(f"Top 5 features:")
        for idx, row in importance_df.head(5).iterrows():
            logger.info(f"  {row['feature']}: {row['importance']:.4f}")
        
        logger.info("✅ Feature analysis complete")
    
    def sanity_checks(self, results: Dict, y_train, y_test):
        """Perform sanity checks"""
        logger.info("\n[STEP 6] Sanity checks...")
        
        # Check 1: Class imbalance
        train_imbalance = y_train.sum() / len(y_train)
        test_imbalance = y_test.sum() / len(y_test)
        logger.info(f"Class balance - Train: {train_imbalance:.2%}, Test: {test_imbalance:.2%}")
        if train_imbalance < 0.1 or train_imbalance > 0.9:
            logger.warning("⚠️  WARNING: Severe class imbalance detected")
        
        # Check 2: Suspiciously high AUC
        for name, metrics in results.items():
            if metrics['auc'] > 0.95:
                logger.warning(f"⚠️  WARNING: {name} has suspiciously high AUC ({metrics['auc']:.4f})")
                logger.warning("    Possible overfitting or data leakage")
        
        # Check 3: Train-test gap (would need train metrics)
        logger.info("✅ Sanity checks complete")
    
    def _plot_confusion_matrices(self, results: Dict, y_test):
        """Plot confusion matrices"""
        fig, axes = plt.subplots(1, 2, figsize=(12, 5))
        
        for idx, (name, metrics) in enumerate(results.items()):
            cm = np.array(metrics['confusion_matrix'])
            sns.heatmap(cm, annot=True, fmt='d', cmap='Blues', ax=axes[idx])
            axes[idx].set_title(f'Confusion Matrix - {name.replace("_", " ").title()}')
            axes[idx].set_ylabel('True Label')
            axes[idx].set_xlabel('Predicted Label')
        
        plt.tight_layout()
        plt.savefig(self.results_dir / 'confusion_matrix.png', dpi=300, bbox_inches='tight')
        plt.close()
        logger.info(f"Saved: confusion_matrix.png")
    
    def _plot_roc_curves(self, results: Dict, y_test):
        """Plot ROC curves"""
        plt.figure(figsize=(8, 6))
        
        for name, metrics in results.items():
            fpr, tpr, _ = roc_curve(y_test, metrics['y_pred_proba'])
            plt.plot(fpr, tpr, label=f'{name.replace("_", " ").title()} (AUC={metrics["auc"]:.3f})')
        
        plt.plot([0, 1], [0, 1], 'k--', label='Random')
        plt.xlabel('False Positive Rate')
        plt.ylabel('True Positive Rate')
        plt.title('ROC Curves')
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(self.results_dir / 'roc_curve.png', dpi=300, bbox_inches='tight')
        plt.close()
        logger.info(f"Saved: roc_curve.png")
    
    def save_results(self, results: Dict, cv_results: Dict):
        """Save metrics to JSON"""
        logger.info("\n[STEP 7] Saving results...")
        
        # Remove non-serializable fields
        save_results = {}
        for name, metrics in results.items():
            save_results[name] = {
                'precision': metrics['precision'],
                'recall': metrics['recall'],
                'f1': metrics['f1'],
                'auc': metrics['auc'],
                'confusion_matrix': metrics['confusion_matrix']
            }
        
        output = {
            'test_results': save_results,
            'cross_validation': cv_results,
            'prediction_horizon': self.prediction_horizon
        }
        
        with open(self.results_dir / 'metrics.json', 'w') as f:
            json.dump(output, f, indent=2)
        
        logger.info(f"✅ Saved: metrics.json")
    
    def generate_summary(self, results: Dict, cv_results: Dict, n_train: int, n_test: int):
        """Generate summary report"""
        logger.info("\n[STEP 8] Generating summary...")
        
        summary = []
        summary.append("="*80)
        summary.append("ELECTROLYSER FAULT PREDICTION - RESULTS SUMMARY")
        summary.append("="*80)
        summary.append("")
        summary.append(f"Prediction Horizon: {self.prediction_horizon} seconds")
        summary.append(f"Training Samples: {n_train}")
        summary.append(f"Test Samples: {n_test}")
        summary.append("")
        summary.append("-"*80)
        summary.append("TEST SET PERFORMANCE")
        summary.append("-"*80)
        
        for name, metrics in results.items():
            summary.append(f"\n{name.replace('_', ' ').upper()}:")
            summary.append(f"  Precision: {metrics['precision']:.4f}")
            summary.append(f"  Recall:    {metrics['recall']:.4f}")
            summary.append(f"  F1 Score:  {metrics['f1']:.4f}")
            summary.append(f"  AUC-ROC:   {metrics['auc']:.4f}")
        
        summary.append("")
        summary.append("-"*80)
        summary.append("CROSS-VALIDATION (3-FOLD)")
        summary.append("-"*80)
        
        for name, cv_metrics in cv_results.items():
            summary.append(f"\n{name.replace('_', ' ').upper()}:")
            summary.append(f"  Mean F1: {cv_metrics['mean_f1']:.4f} ± {cv_metrics['std_f1']:.4f}")
        
        summary.append("")
        summary.append("-"*80)
        summary.append("KEY OBSERVATIONS")
        summary.append("-"*80)
        
        best_model = max(results.items(), key=lambda x: x[1]['f1'])
        summary.append(f"• Best Model: {best_model[0].replace('_', ' ').title()} (F1={best_model[1]['f1']:.4f})")
        
        summary.append("")
        summary.append("-"*80)
        summary.append("LIMITATIONS")
        summary.append("-"*80)
        summary.append("• Synthetic data only (no real-world validation)")
        summary.append("• Simulation may not capture all real-world complexities")
        summary.append("• Limited fault types (15 types simulated)")
        summary.append("• Time-based split may not reflect deployment scenarios")
        summary.append("")
        summary.append("="*80)
        
        summary_text = "\n".join(summary)
        
        with open(self.results_dir / 'summary.txt', 'w') as f:
            f.write(summary_text)
        
        print("\n" + summary_text)
        logger.info("✅ Summary generated")


def main():
    """Run complete pipeline"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Train and evaluate ML models')
    parser.add_argument('--dataset', type=str, default='data/generated/dataset_v1.csv')
    parser.add_argument('--horizon', type=int, default=60)
    
    args = parser.parse_args()
    
    pipeline = MLPipeline(args.dataset, args.horizon)
    pipeline.run_full_pipeline()


if __name__ == '__main__':
    main()

# Made with Bob

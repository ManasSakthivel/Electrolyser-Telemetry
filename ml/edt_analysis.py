"""
Early Detection Time (EDT) Analysis Module
Provides accurate EDT computation and visualization for validating early prediction claims
"""

import logging
import json
import numpy as np  # type: ignore
import pandas as pd  # type: ignore
import matplotlib.pyplot as plt  # type: ignore
import seaborn as sns  # type: ignore
from pathlib import Path
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger(__name__)

sns.set_style("whitegrid")
plt.rcParams['figure.dpi'] = 300
plt.rcParams['font.size'] = 10


class EDTAnalyzer:
    """
    Analyzes Early Detection Time for fault prediction models
    Validates that predictions occur BEFORE fault onset
    """
    
    def __init__(self, results_dir: str = "research/results"):
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        logger.info("EDTAnalyzer initialized")
    
    def compute_edt(self, df: pd.DataFrame, y_pred_proba: np.ndarray,
                   threshold: float = 0.5) -> Dict:
        """
        Compute Early Detection Time metrics
        
        Args:
            df: DataFrame with columns: timestamp, time_to_failure, run_id
            y_pred_proba: Model prediction probabilities (aligned with df)
            threshold: Prediction threshold
            
        Returns:
            Dictionary with EDT metrics and per-run analysis
        """
        logger.info("Computing Early Detection Time metrics...")
        
        df = df.copy()
        df['pred_proba'] = y_pred_proba
        df['predicted'] = (y_pred_proba > threshold).astype(int)
        
        edt_results = []
        
        # Analyze each run separately
        for run_id in df['run_id'].unique():
            run_df = df[df['run_id'] == run_id].sort_values('timestamp').reset_index(drop=True)
            
            result = self._analyze_single_run(run_df, run_id)
            if result is not None:
                edt_results.append(result)
        
        # Compute aggregate metrics
        metrics = self._compute_aggregate_metrics(edt_results)
        
        logger.info(f"✅ EDT Analysis Complete:")
        logger.info(f"   Mean EDT: {metrics['mean_edt']:.1f}s")
        logger.info(f"   Median EDT: {metrics['median_edt']:.1f}s")
        logger.info(f"   Early Prediction Rate: {metrics['early_prediction_rate']:.1%}")
        
        return metrics
    
    def _analyze_single_run(self, run_df: pd.DataFrame, run_id: str) -> Optional[Dict]:
        """Analyze a single simulation run"""
        ttf = run_df['time_to_failure'].values
        timestamps = run_df['timestamp'].values
        
        # Find fault onset: where TTF first becomes finite and decreasing
        fault_onset_idx = None
        for i in range(1, len(ttf)):
            # Fault onset is when TTF transitions from large/inf to decreasing
            if ttf[i] < ttf[i-1] and ttf[i] < 1000:
                fault_onset_idx = i
                break
        
        if fault_onset_idx is None:
            return None  # No fault in this run
        
        fault_onset_time = timestamps[fault_onset_idx]
        
        # Find first prediction
        pred_indices = run_df[run_df['predicted'] == 1].index.tolist()
        
        if len(pred_indices) == 0:
            return {
                'run_id': run_id,
                'fault_onset_time': float(fault_onset_time),
                'prediction_time': None,
                'edt': None,
                'status': 'missed'
            }
        
        first_pred_idx = pred_indices[0]
        prediction_time = timestamps[first_pred_idx]
        
        # Compute EDT
        edt = fault_onset_time - prediction_time
        
        # Determine status
        if edt > 0:
            status = 'early'
        elif edt < 0:
            status = 'late'
        else:
            status = 'exact'
        
        return {
            'run_id': run_id,
            'fault_onset_time': float(fault_onset_time),
            'prediction_time': float(prediction_time),
            'edt': float(edt),
            'status': status
        }
    
    def _compute_aggregate_metrics(self, edt_results: List[Dict]) -> Dict:
        """Compute aggregate EDT metrics"""
        valid_edts = [r['edt'] for r in edt_results if r['edt'] is not None]
        early_predictions = [r for r in edt_results if r['status'] == 'early']
        
        metrics = {
            'mean_edt': float(np.mean(valid_edts)) if valid_edts else 0.0,
            'median_edt': float(np.median(valid_edts)) if valid_edts else 0.0,
            'std_edt': float(np.std(valid_edts)) if valid_edts else 0.0,
            'min_edt': float(np.min(valid_edts)) if valid_edts else 0.0,
            'max_edt': float(np.max(valid_edts)) if valid_edts else 0.0,
            'total_faults': len(edt_results),
            'early_predictions': len(early_predictions),
            'missed_predictions': len([r for r in edt_results if r['status'] == 'missed']),
            'late_predictions': len([r for r in edt_results if r['status'] == 'late']),
            'early_prediction_rate': len(early_predictions) / len(edt_results) if edt_results else 0.0,
            'per_run_results': edt_results
        }
        
        return metrics
    
    def validate_early_prediction_claim(self, metrics: Dict) -> Dict:
        """
        Validate that predictions truly occur before faults
        
        Returns:
            Validation results with pass/fail status
        """
        logger.info("\n" + "="*80)
        logger.info("VALIDATING EARLY PREDICTION CLAIM")
        logger.info("="*80)
        
        validation = {
            'claim_validated': False,
            'checks': {}
        }
        
        # Check 1: Mean EDT > 0
        check1 = metrics['mean_edt'] > 0
        validation['checks']['mean_edt_positive'] = {
            'passed': check1,
            'value': metrics['mean_edt'],
            'message': f"Mean EDT = {metrics['mean_edt']:.1f}s {'✅ PASS' if check1 else '❌ FAIL'}"
        }
        logger.info(f"Check 1: {validation['checks']['mean_edt_positive']['message']}")
        
        # Check 2: Early prediction rate > 70%
        check2 = metrics['early_prediction_rate'] > 0.70
        validation['checks']['early_rate_sufficient'] = {
            'passed': check2,
            'value': metrics['early_prediction_rate'],
            'message': f"Early prediction rate = {metrics['early_prediction_rate']:.1%} {'✅ PASS' if check2 else '❌ FAIL'}"
        }
        logger.info(f"Check 2: {validation['checks']['early_rate_sufficient']['message']}")
        
        # Check 3: No negative EDT on average
        check3 = metrics['mean_edt'] >= 0
        validation['checks']['no_negative_edt'] = {
            'passed': check3,
            'value': metrics['mean_edt'],
            'message': f"Mean EDT non-negative {'✅ PASS' if check3 else '❌ FAIL'}"
        }
        logger.info(f"Check 3: {validation['checks']['no_negative_edt']['message']}")
        
        # Check 4: Meaningful early warning (> 10s)
        check4 = metrics['mean_edt'] > 10
        validation['checks']['meaningful_warning'] = {
            'passed': check4,
            'value': metrics['mean_edt'],
            'message': f"Mean EDT > 10s {'✅ PASS' if check4 else '❌ FAIL'}"
        }
        logger.info(f"Check 4: {validation['checks']['meaningful_warning']['message']}")
        
        # Overall validation
        validation['claim_validated'] = all([check1, check2, check3, check4])
        
        logger.info("\n" + "="*80)
        if validation['claim_validated']:
            logger.info("✅ EARLY PREDICTION CLAIM VALIDATED")
        else:
            logger.warning("❌ EARLY PREDICTION CLAIM NOT VALIDATED")
        logger.info("="*80 + "\n")
        
        return validation
    
    def plot_timeline(self, df: pd.DataFrame, y_pred_proba: np.ndarray,
                     metrics: Dict, num_runs: int = 10, threshold: float = 0.5):
        """
        Generate timeline visualization showing predictions vs fault onset
        
        Args:
            df: DataFrame with timestamp, time_to_failure, run_id
            y_pred_proba: Model predictions
            metrics: EDT metrics from compute_edt()
            num_runs: Number of runs to plot
            threshold: Prediction threshold
        """
        logger.info("Generating timeline visualization...")
        
        per_run_results = metrics['per_run_results'][:num_runs]
        
        fig, ax = plt.subplots(figsize=(14, 8))
        
        for idx, result in enumerate(per_run_results):
            y_pos = idx
            
            if result['status'] == 'missed':
                # Plot fault onset only
                ax.plot(result['fault_onset_time'], y_pos, 'rx', 
                       markersize=12, markeredgewidth=2, label='Fault Onset' if idx == 0 else '')
                ax.text(result['fault_onset_time'] + 5, y_pos, 'MISSED', 
                       fontsize=8, color='red', va='center')
            else:
                # Plot prediction and fault onset
                pred_time = result['prediction_time']
                fault_time = result['fault_onset_time']
                edt = result['edt']
                
                # Draw timeline
                color = 'green' if result['status'] == 'early' else 'red'
                ax.plot([pred_time, fault_time], [y_pos, y_pos], 
                       color=color, linewidth=2, alpha=0.6)
                
                # Mark prediction
                ax.plot(pred_time, y_pos, 'go', markersize=10, 
                       label='Prediction' if idx == 0 else '')
                
                # Mark fault onset
                ax.plot(fault_time, y_pos, 'rx', markersize=12, markeredgewidth=2,
                       label='Fault Onset' if idx == 0 else '')
                
                # Annotate EDT
                mid_point = (pred_time + fault_time) / 2
                ax.text(mid_point, y_pos + 0.3, f'{edt:.0f}s', 
                       fontsize=8, ha='center', color=color, weight='bold')
        
        ax.set_xlabel('Time (seconds)', fontsize=12)
        ax.set_ylabel('Run ID', fontsize=12)
        ax.set_title('Early Prediction Timeline Validation\n' + 
                    f'Mean EDT: {metrics["mean_edt"]:.1f}s | ' +
                    f'Early Rate: {metrics["early_prediction_rate"]:.1%}',
                    fontsize=14, weight='bold')
        ax.set_yticks(range(len(per_run_results)))
        ax.set_yticklabels([r['run_id'] for r in per_run_results])
        ax.legend(loc='upper right', fontsize=10)
        ax.grid(True, alpha=0.3, axis='x')
        
        plt.tight_layout()
        output_path = self.results_dir / 'early_prediction_timeline.png'
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        logger.info(f"✅ Saved: {output_path}")
    
    def plot_edt_distribution(self, metrics: Dict):
        """Plot EDT distribution histogram"""
        logger.info("Generating EDT distribution plot...")
        
        edts = [r['edt'] for r in metrics['per_run_results'] if r['edt'] is not None]
        
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
        
        # Histogram
        ax1.hist(edts, bins=20, edgecolor='black', alpha=0.7, color='steelblue')
        ax1.axvline(metrics['mean_edt'], color='red', linestyle='--', 
                   linewidth=2, label=f'Mean: {metrics["mean_edt"]:.1f}s')
        ax1.axvline(metrics['median_edt'], color='green', linestyle='--', 
                   linewidth=2, label=f'Median: {metrics["median_edt"]:.1f}s')
        ax1.set_xlabel('Early Detection Time (seconds)', fontsize=12)
        ax1.set_ylabel('Frequency', fontsize=12)
        ax1.set_title('EDT Distribution', fontsize=14, weight='bold')
        ax1.legend()
        ax1.grid(True, alpha=0.3, axis='y')
        
        # Box plot
        ax2.boxplot(edts, vert=True)
        ax2.set_ylabel('Early Detection Time (seconds)', fontsize=12)
        ax2.set_title('EDT Box Plot', fontsize=14, weight='bold')
        ax2.grid(True, alpha=0.3, axis='y')
        
        plt.tight_layout()
        output_path = self.results_dir / 'edt_distribution.png'
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        logger.info(f"✅ Saved: {output_path}")
    
    def save_metrics(self, metrics: Dict, validation: Dict):
        """Save EDT metrics and validation results to JSON"""
        output = {
            'edt_metrics': {
                'mean_edt': metrics['mean_edt'],
                'median_edt': metrics['median_edt'],
                'std_edt': metrics['std_edt'],
                'min_edt': metrics['min_edt'],
                'max_edt': metrics['max_edt'],
                'total_faults': metrics['total_faults'],
                'early_predictions': metrics['early_predictions'],
                'missed_predictions': metrics['missed_predictions'],
                'late_predictions': metrics['late_predictions'],
                'early_prediction_rate': metrics['early_prediction_rate']
            },
            'validation': validation,
            'per_run_results': metrics['per_run_results']
        }
        
        output_path = self.results_dir / 'early_detection_metrics.json'
        with open(output_path, 'w') as f:
            json.dump(output, f, indent=2)
        
        logger.info(f"✅ Saved: {output_path}")


def main():
    """Test EDT analyzer"""
    import sys
    from pathlib import Path
    
    # This would be called from the main pipeline
    print("EDT Analyzer module loaded successfully")
    print("Use EDTAnalyzer class to compute and visualize early detection time")


if __name__ == '__main__':
    main()

# Made with Bob
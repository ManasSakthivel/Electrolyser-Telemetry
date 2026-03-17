"""
Test script for EDT computation pipeline
Validates that early detection time is computed correctly
"""

import sys
from pathlib import Path
import pandas as pd  # type: ignore
import numpy as np  # type: ignore

# Add project root to path
sys.path.append(str(Path(__file__).parent))

from ml.edt_analysis import EDTAnalyzer


def create_synthetic_test_data():
    """Create synthetic data to test EDT computation"""
    print("Creating synthetic test data...")
    
    data = []
    
    # Run 1: Early prediction (EDT = 45s)
    for t in range(0, 200):
        ttf = max(0, 150 - t) if t >= 105 else 9999
        data.append({
            'timestamp': t,
            'run_id': 'run_001',
            'time_to_failure': ttf,
            'sensor_value': 1.0 + 0.01 * t
        })
    
    # Run 2: Early prediction (EDT = 30s)
    for t in range(0, 200):
        ttf = max(0, 180 - t) if t >= 150 else 9999
        data.append({
            'timestamp': t + 200,
            'run_id': 'run_002',
            'time_to_failure': ttf,
            'sensor_value': 1.0 + 0.01 * t
        })
    
    # Run 3: Missed prediction
    for t in range(0, 200):
        ttf = max(0, 100 - t) if t >= 100 else 9999
        data.append({
            'timestamp': t + 400,
            'run_id': 'run_003',
            'time_to_failure': ttf,
            'sensor_value': 1.0
        })
    
    df = pd.DataFrame(data)
    
    # Create synthetic predictions
    # Run 1: Predict at t=105 (fault at t=150, EDT=45)
    # Run 2: Predict at t=350 (fault at t=380, EDT=30)
    # Run 3: Never predict (missed)
    
    pred_proba = np.zeros(len(df))
    pred_proba[(df['run_id'] == 'run_001') & (df['timestamp'] >= 105)] = 0.8
    pred_proba[(df['run_id'] == 'run_002') & (df['timestamp'] >= 350)] = 0.7
    # run_003 stays at 0 (missed)
    
    return df, pred_proba


def test_edt_computation():
    """Test EDT computation"""
    print("\n" + "="*80)
    print("TESTING EDT COMPUTATION")
    print("="*80)
    
    # Create test data
    df, pred_proba = create_synthetic_test_data()
    
    print(f"\nTest data created:")
    print(f"  Total samples: {len(df)}")
    print(f"  Runs: {df['run_id'].nunique()}")
    
    # Initialize analyzer
    analyzer = EDTAnalyzer(results_dir="test_results")
    
    # Compute EDT
    print("\nComputing EDT metrics...")
    metrics = analyzer.compute_edt(df, pred_proba, threshold=0.5)
    
    # Validate results
    print("\n" + "-"*80)
    print("RESULTS:")
    print("-"*80)
    print(f"Mean EDT: {metrics['mean_edt']:.1f}s")
    print(f"Median EDT: {metrics['median_edt']:.1f}s")
    print(f"Std EDT: {metrics['std_edt']:.1f}s")
    print(f"Early predictions: {metrics['early_predictions']}/{metrics['total_faults']}")
    print(f"Missed predictions: {metrics['missed_predictions']}")
    print(f"Early prediction rate: {metrics['early_prediction_rate']:.1%}")
    
    # Validate claim
    print("\n" + "-"*80)
    print("VALIDATION:")
    print("-"*80)
    validation = analyzer.validate_early_prediction_claim(metrics)
    
    # Generate plots
    print("\n" + "-"*80)
    print("GENERATING PLOTS:")
    print("-"*80)
    analyzer.plot_timeline(df, pred_proba, metrics, num_runs=3)
    analyzer.plot_edt_distribution(metrics)
    
    # Save metrics
    analyzer.save_metrics(metrics, validation)
    
    # Check expected values
    print("\n" + "="*80)
    print("VALIDATION CHECKS:")
    print("="*80)
    
    checks_passed = 0
    checks_total = 0
    
    # Check 1: Mean EDT should be around 37.5s ((45+30)/2)
    checks_total += 1
    expected_mean = 37.5
    if abs(metrics['mean_edt'] - expected_mean) < 5:
        print(f"✅ Mean EDT is correct: {metrics['mean_edt']:.1f}s (expected ~{expected_mean}s)")
        checks_passed += 1
    else:
        print(f"❌ Mean EDT is incorrect: {metrics['mean_edt']:.1f}s (expected ~{expected_mean}s)")
    
    # Check 2: Should have 2 early predictions
    checks_total += 1
    if metrics['early_predictions'] == 2:
        print(f"✅ Early predictions count is correct: {metrics['early_predictions']}")
        checks_passed += 1
    else:
        print(f"❌ Early predictions count is incorrect: {metrics['early_predictions']} (expected 2)")
    
    # Check 3: Should have 1 missed prediction
    checks_total += 1
    if metrics['missed_predictions'] == 1:
        print(f"✅ Missed predictions count is correct: {metrics['missed_predictions']}")
        checks_passed += 1
    else:
        print(f"❌ Missed predictions count is incorrect: {metrics['missed_predictions']} (expected 1)")
    
    # Check 4: Early prediction rate should be 66.7%
    checks_total += 1
    expected_rate = 2/3
    if abs(metrics['early_prediction_rate'] - expected_rate) < 0.01:
        print(f"✅ Early prediction rate is correct: {metrics['early_prediction_rate']:.1%}")
        checks_passed += 1
    else:
        print(f"❌ Early prediction rate is incorrect: {metrics['early_prediction_rate']:.1%} (expected {expected_rate:.1%})")
    
    # Check 5: Validation should pass
    checks_total += 1
    if validation['claim_validated']:
        print(f"✅ Early prediction claim validated")
        checks_passed += 1
    else:
        print(f"❌ Early prediction claim NOT validated")
    
    print("\n" + "="*80)
    print(f"FINAL RESULT: {checks_passed}/{checks_total} checks passed")
    print("="*80)
    
    if checks_passed == checks_total:
        print("\n✅ ALL TESTS PASSED - EDT COMPUTATION IS CORRECT")
        return True
    else:
        print("\n❌ SOME TESTS FAILED - REVIEW EDT COMPUTATION")
        return False


if __name__ == '__main__':
    success = test_edt_computation()
    sys.exit(0 if success else 1)

# Made with Bob
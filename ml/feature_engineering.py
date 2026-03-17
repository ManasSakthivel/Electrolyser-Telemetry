"""
Feature Engineering Module
Transforms raw sensor data into ML-ready features
"""

import logging
import pandas as pd  # type: ignore
import numpy as np  # type: ignore
from typing import List, Dict, Optional
from scipy import stats  # type: ignore

logger = logging.getLogger(__name__)


class FeatureEngineer:
    """
    Feature engineering for electrolyser time-series data
    Creates rolling statistics, temporal features, and domain-specific features
    """
    
    def __init__(self, window_sizes: List[int] = [10, 30, 60]):
        """
        Initialize feature engineer
        
        Args:
            window_sizes: List of window sizes (in seconds) for rolling features
        """
        self.window_sizes = window_sizes
        logger.info(f"FeatureEngineer initialized with windows: {window_sizes}")
    
    def engineer_features(self, df: pd.DataFrame, 
                         include_labels: bool = True) -> pd.DataFrame:
        """
        Engineer features from raw sensor data
        
        Args:
            df: Raw sensor DataFrame
            include_labels: Whether to include label columns
            
        Returns:
            DataFrame with engineered features
        """
        logger.info(f"Engineering features for {len(df)} samples...")
        
        # Sort by electrolyser_id and timestamp
        df = df.sort_values(['electrolyser_id', 'timestamp']).reset_index(drop=True)
        
        # Create copy for feature engineering
        features_df = df.copy()
        
        # 1. Rolling statistics for each sensor
        sensor_cols = [
            'cell_1_voltage', 'cell_2_voltage', 'cell_3_voltage', 
            'cell_4_voltage', 'cell_5_voltage',
            'stack_current', 'stack_voltage', 'stack_temperature', 
            'stack_pressure', 'h2_flow_rate', 'o2_flow_rate', 
            'water_flow', 'tank_pressure', 'irradiance'
        ]
        
        for col in sensor_cols:
            features_df = self._add_rolling_features(features_df, col)
        
        # 2. Cell voltage statistics
        features_df = self._add_cell_voltage_features(features_df)
        
        # 3. Temporal features
        features_df = self._add_temporal_features(features_df)
        
        # 4. Domain-specific features
        features_df = self._add_domain_features(features_df)
        
        # 5. Lag features
        features_df = self._add_lag_features(features_df, sensor_cols)
        
        # Drop rows with NaN (from rolling windows)
        max_window = max(self.window_sizes)
        features_df = features_df.groupby('electrolyser_id').apply(
            lambda x: x.iloc[max_window:]
        ).reset_index(drop=True)
        
        # Select feature columns
        if include_labels:
            label_cols = ['fault_type', 'fault_active', 'fault_severity', 
                         'time_to_failure', 'is_tripped']
        else:
            label_cols = []
        
        # Get all feature columns (exclude metadata and labels)
        exclude_cols = ['timestamp', 'electrolyser_id'] + label_cols
        feature_cols = [col for col in features_df.columns if col not in exclude_cols]
        
        logger.info(f"Generated {len(feature_cols)} features")
        
        return features_df
    
    def _add_rolling_features(self, df: pd.DataFrame, col: str) -> pd.DataFrame:
        """Add rolling statistics for a column"""
        for window in self.window_sizes:
            # Mean
            df[f'{col}_mean_{window}s'] = df.groupby('electrolyser_id')[col].transform(
                lambda x: x.rolling(window, min_periods=1).mean()
            )
            
            # Std
            df[f'{col}_std_{window}s'] = df.groupby('electrolyser_id')[col].transform(
                lambda x: x.rolling(window, min_periods=1).std()
            )
            
            # Min
            df[f'{col}_min_{window}s'] = df.groupby('electrolyser_id')[col].transform(
                lambda x: x.rolling(window, min_periods=1).min()
            )
            
            # Max
            df[f'{col}_max_{window}s'] = df.groupby('electrolyser_id')[col].transform(
                lambda x: x.rolling(window, min_periods=1).max()
            )
            
            # Slope (linear regression)
            df[f'{col}_slope_{window}s'] = df.groupby('electrolyser_id')[col].transform(
                lambda x: x.rolling(window, min_periods=2).apply(
                    lambda y: np.polyfit(range(len(y)), y, 1)[0] if len(y) > 1 else 0
                )
            )
        
        return df
    
    def _add_cell_voltage_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add features related to cell voltage distribution"""
        cell_cols = ['cell_1_voltage', 'cell_2_voltage', 'cell_3_voltage', 
                     'cell_4_voltage', 'cell_5_voltage']
        
        # Cell voltage spread (max - min)
        df['cell_voltage_spread'] = df[cell_cols].max(axis=1) - df[cell_cols].min(axis=1)
        
        # Cell voltage std
        df['cell_voltage_std'] = df[cell_cols].std(axis=1)
        
        # Cell voltage skewness
        df['cell_voltage_skew'] = df[cell_cols].apply(lambda x: stats.skew(x), axis=1)
        
        # Cell voltage kurtosis
        df['cell_voltage_kurt'] = df[cell_cols].apply(lambda x: stats.kurtosis(x), axis=1)
        
        # Deviation from mean
        cell_mean = df[cell_cols].mean(axis=1)
        for i, col in enumerate(cell_cols, 1):
            df[f'cell_{i}_deviation'] = df[col] - cell_mean
        
        return df
    
    def _add_temporal_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add temporal features"""
        # Time since start (per run)
        df['time_since_start'] = df.groupby('electrolyser_id')['timestamp'].transform(
            lambda x: x - x.iloc[0]
        )
        
        # Time of day (cyclical encoding)
        # Assuming fast day cycle from config
        day_period = 600.0  # seconds
        df['time_sin'] = np.sin(2 * np.pi * df['timestamp'] / day_period)
        df['time_cos'] = np.cos(2 * np.pi * df['timestamp'] / day_period)
        
        return df
    
    def _add_domain_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add domain-specific electrolyser features"""
        # Power efficiency deviation
        df['efficiency_deviation'] = df['efficiency'] - df['efficiency'].rolling(30, min_periods=1).mean()
        
        # H2/O2 ratio deviation from ideal (2.0)
        df['h2_o2_ratio_deviation'] = np.abs(df['h2_o2_ratio'] - 2.0)
        
        # Current density (simplified)
        df['current_density'] = df['stack_current'] / 5.0  # assuming 5 cells
        
        # Voltage efficiency (actual vs theoretical)
        df['voltage_efficiency'] = 1.23 * 5 / df['stack_voltage']  # 1.23V per cell theoretical
        
        # Temperature gradient (change rate)
        df['temp_gradient'] = df.groupby('electrolyser_id')['stack_temperature'].diff()
        
        # Pressure gradient
        df['pressure_gradient'] = df.groupby('electrolyser_id')['tank_pressure'].diff()
        
        # Flow imbalance
        df['flow_imbalance'] = np.abs(df['h2_flow_rate'] - 2 * df['o2_flow_rate'])
        
        # Power factor
        df['power_factor'] = df['power'] / (df['stack_voltage'] * df['stack_current'] + 1e-6)
        
        return df
    
    def _add_lag_features(self, df: pd.DataFrame, cols: List[str], 
                         lags: List[int] = [1, 5, 10]) -> pd.DataFrame:
        """Add lagged features"""
        for col in cols:
            for lag in lags:
                df[f'{col}_lag_{lag}'] = df.groupby('electrolyser_id')[col].shift(lag)
        
        return df
    
    def get_feature_names(self, df: pd.DataFrame) -> List[str]:
        """Get list of feature column names"""
        exclude_cols = ['timestamp', 'electrolyser_id', 'fault_type', 
                       'fault_active', 'fault_severity', 'time_to_failure', 'is_tripped']
        return [col for col in df.columns if col not in exclude_cols]


def main():
    """Test feature engineering"""
    import sys
    from pathlib import Path
    
    # Load dataset
    data_path = Path('data/generated/electrolyser_dataset.parquet')
    if not data_path.exists():
        print(f"Dataset not found at {data_path}")
        print("Please run dataset_generator.py first")
        sys.exit(1)
    
    df = pd.read_parquet(data_path)
    print(f"Loaded dataset: {df.shape}")
    
    # Engineer features
    engineer = FeatureEngineer(window_sizes=[10, 30, 60])
    features_df = engineer.engineer_features(df)
    
    print(f"\nFeatures engineered: {features_df.shape}")
    print(f"\nFeature columns ({len(engineer.get_feature_names(features_df))}):")
    for col in engineer.get_feature_names(features_df)[:20]:
        print(f"  - {col}")
    print("  ...")
    
    # Save
    output_path = Path('data/generated/electrolyser_features.parquet')
    features_df.to_parquet(output_path, index=False)
    print(f"\nFeatures saved to {output_path}")


if __name__ == '__main__':
    main()

# Made with Bob

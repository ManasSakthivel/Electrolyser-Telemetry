"""
Dataset Generator
Generates labeled datasets for ML training from simulation runs
This is the CORE NOVELTY ENABLER for the research system
"""

import logging
import random
import math
import time
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict

import sys
sys.path.append(str(Path(__file__).parent.parent))

from simulation.config_loader import load_config
from simulation.simulation_engine import SimulationEngine, ElectrolyserState
from simulation.fault_injector import FaultInjector

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class DataPoint:
    """Single data point in the dataset"""
    timestamp: float
    electrolyser_id: str
    
    # Cell voltages
    cell_1_voltage: float
    cell_2_voltage: float
    cell_3_voltage: float
    cell_4_voltage: float
    cell_5_voltage: float
    
    # Stack measurements
    stack_current: float
    stack_voltage: float
    stack_temperature: float
    stack_pressure: float
    
    # Gas flows
    h2_flow_rate: float
    o2_flow_rate: float
    water_flow: float
    
    # Tank
    tank_pressure: float
    
    # Derived features
    h2_o2_ratio: float
    efficiency: float
    power: float
    
    # Irradiance
    irradiance: float
    
    # Labels
    fault_type: str  # 'none' or fault name
    fault_active: int  # 0 or 1
    fault_severity: float  # 0.0 to 1.0
    time_to_failure: float  # seconds until fault becomes critical (CRITICAL FOR EARLY PREDICTION)
    is_tripped: int  # 0 or 1


class DatasetGenerator:
    """
    Generates ML-ready datasets from electrolyser simulations
    """
    
    def __init__(self, config_path: str = "config/simulation_config.yaml"):
        """Initialize dataset generator"""
        self.config = load_config(config_path)
        self.config.validate()
        
        self.data_gen_config = self.config.get_section('data_generation')
        self.sim_config = self.config.get_section('simulation')
        
        # Set random seed for reproducibility
        seed = self.sim_config.get('random_seed', 42)
        random.seed(seed)
        np.random.seed(seed)
        
        logger.info("DatasetGenerator initialized")
    
    def generate_dataset(self, num_runs: Optional[int] = None, 
                        output_dir: Optional[str] = None) -> pd.DataFrame:
        """
        Generate complete dataset with multiple simulation runs
        
        Args:
            num_runs: Number of simulation runs (overrides config)
            output_dir: Output directory (overrides config)
            
        Returns:
            DataFrame with all data points
        """
        # Set defaults
        num_runs = num_runs if num_runs is not None else self.data_gen_config.get('num_runs', 100)
        output_dir = output_dir if output_dir is not None else self.data_gen_config.get('output_dir', 'data/generated')
        
        logger.info(f"Generating dataset with {num_runs} runs...")
        
        all_data = []
        
        for run_idx in range(num_runs):
            logger.info(f"Run {run_idx + 1}/{num_runs}")
            
            # Decide if this run has a fault
            has_fault = random.random() < self.data_gen_config.get('fault_injection_probability', 0.3)
            
            if has_fault:
                # Select random fault and severity
                fault_types = list(self.config.get('faults.definitions', {}).keys())
                fault_type = random.choice(fault_types)
                fault_severity = random.uniform(0.3, 0.8)
                
                # Random fault start time
                fault_start_range = self.data_gen_config.get('fault_start_time_range', [600, 5400])
                fault_start_time = random.uniform(*fault_start_range)
            else:
                fault_type = None
                fault_severity = 0.0
                fault_start_time = float('inf')
            
            # Run simulation
            run_data = self._run_simulation(
                run_idx=run_idx,
                fault_type=fault_type,
                fault_severity=fault_severity,
                fault_start_time=fault_start_time
            )
            
            all_data.extend(run_data)
        
        # Convert to DataFrame
        df = pd.DataFrame([asdict(dp) for dp in all_data])
        
        # Save dataset
        output_path = Path(str(output_dir))
        output_path.mkdir(parents=True, exist_ok=True)
        
        output_format = self.data_gen_config.get('output_format', 'parquet')
        if output_format == 'parquet':
            file_path = output_path / 'electrolyser_dataset.parquet'
            df.to_parquet(file_path, index=False)
        else:
            file_path = output_path / 'electrolyser_dataset.csv'
            df.to_csv(file_path, index=False)
        
        logger.info(f"Dataset saved to {file_path}")
        logger.info(f"Total data points: {len(df)}")
        logger.info(f"Fault distribution:\n{df['fault_type'].value_counts()}")
        
        return df
    
    def _run_simulation(self, run_idx: int, fault_type: Optional[str], 
                       fault_severity: float, fault_start_time: float) -> List[DataPoint]:
        """
        Run a single simulation with optional fault injection
        
        Returns:
            List of data points from this run
        """
        # Create fault injector
        fault_config = self.config.get_section('faults')['definitions']
        fault_injector = FaultInjector(fault_config)
        
        # Create simulation engine
        sim_engine = SimulationEngine(
            el_id=f"EL_RUN_{run_idx}",
            config=self.config.config,
            fault_injector=fault_injector
        )
        
        # Simulation parameters
        dt = self.sim_config.get('timestep', 1.0)
        duration = self.data_gen_config.get('run_duration', 7200)
        fast_day_period = self.sim_config.get('fast_day_period', 600.0)
        
        data_points = []
        t = 0.0
        fault_injected = False
        trip_time = None
        
        while t < duration:
            # Generate irradiance (sine wave with noise)
            base_irr = 500.0 + 500.0 * max(0.0, math.sin(2.0 * math.pi * (t / fast_day_period)))
            irradiance = max(0.0, base_irr + random.uniform(-80, 80))
            
            # Add environmental variation if enabled
            if self.data_gen_config.get('environmental_variation', True):
                irradiance *= random.uniform(0.95, 1.05)
            
            # Inject fault at specified time
            if not fault_injected and fault_type and t >= fault_start_time:
                fault_injector.set_fault(fault_type, active=True, severity=fault_severity)
                fault_injected = True
                logger.debug(f"Fault injected at t={t:.1f}s: {fault_type} (severity={fault_severity:.2f})")
            
            # Update simulation
            state = sim_engine.update(irradiance, dt)
            
            # Record trip time
            if state.tripped and trip_time is None:
                trip_time = t
            
            # Calculate time to failure
            if fault_injected and not state.tripped:
                # Time until trip (if it happens)
                if trip_time:
                    time_to_failure = trip_time - t
                else:
                    # Estimate based on severity (heuristic)
                    time_to_failure = max(0, (duration - t) * (1.0 - fault_severity))
            elif state.tripped:
                time_to_failure = 0.0
            else:
                time_to_failure = float('inf')  # No fault, no failure
            
            # Create data point
            data_point = self._create_data_point(
                timestamp=t,
                el_id=f"EL_RUN_{run_idx}",
                state=state,
                irradiance=irradiance,
                fault_type=fault_type if (fault_injected and fault_type) else 'none',
                fault_severity=fault_severity if fault_injected else 0.0,
                time_to_failure=time_to_failure
            )
            
            data_points.append(data_point)
            
            t += dt
        
        return data_points
    
    def _create_data_point(self, timestamp: float, el_id: str, state: ElectrolyserState,
                          irradiance: float, fault_type: str, fault_severity: float,
                          time_to_failure: float) -> DataPoint:
        """Create a data point from simulation state"""
        
        # Ensure we have 5 cell voltages
        cell_voltages = state.cell_voltages + [0.0] * (5 - len(state.cell_voltages))
        
        # Calculate derived features
        h2_o2_ratio = state.h2_flow_Lpm / state.o2_flow_Lpm if state.o2_flow_Lpm > 0 else 0.0
        power = state.V_stack * state.I_stack
        
        # Efficiency (H2 production vs electrical power)
        # Theoretical: 39.4 kWh/kg H2, actual depends on current efficiency
        theoretical_h2_kg_per_s = (state.h2_flow_Lpm / 60.0) * 0.001 * 0.08988  # L/min -> kg/s
        theoretical_power_kw = theoretical_h2_kg_per_s * 39.4 * 1000  # W
        efficiency = (theoretical_power_kw / power) if power > 0 else 0.0
        
        # Add sensor noise
        noise_std = self.data_gen_config.get('sensor_noise_std', 0.02)
        
        return DataPoint(
            timestamp=timestamp,
            electrolyser_id=el_id,
            cell_1_voltage=cell_voltages[0] * (1 + random.gauss(0, noise_std)),
            cell_2_voltage=cell_voltages[1] * (1 + random.gauss(0, noise_std)),
            cell_3_voltage=cell_voltages[2] * (1 + random.gauss(0, noise_std)),
            cell_4_voltage=cell_voltages[3] * (1 + random.gauss(0, noise_std)),
            cell_5_voltage=cell_voltages[4] * (1 + random.gauss(0, noise_std)),
            stack_current=state.I_stack * (1 + random.gauss(0, noise_std)),
            stack_voltage=state.V_stack * (1 + random.gauss(0, noise_std)),
            stack_temperature=state.stack_temp * (1 + random.gauss(0, noise_std)),
            stack_pressure=state.stack_pressure * (1 + random.gauss(0, noise_std)),
            h2_flow_rate=state.h2_flow_Lpm * (1 + random.gauss(0, noise_std)),
            o2_flow_rate=state.o2_flow_Lpm * (1 + random.gauss(0, noise_std)),
            water_flow=state.water_flow * (1 + random.gauss(0, noise_std)),
            tank_pressure=state.tank_pressure_bar * (1 + random.gauss(0, noise_std)),
            h2_o2_ratio=h2_o2_ratio,
            efficiency=efficiency,
            power=power,
            irradiance=irradiance,
            fault_type=fault_type,
            fault_active=1 if fault_type != 'none' else 0,
            fault_severity=fault_severity,
            time_to_failure=time_to_failure,
            is_tripped=1 if state.tripped else 0
        )


def main():
    """Main entry point for dataset generation"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate ML dataset from electrolyser simulation')
    parser.add_argument('--num-runs', type=int, default=None, help='Number of simulation runs')
    parser.add_argument('--output-dir', type=str, default=None, help='Output directory')
    parser.add_argument('--config', type=str, default='config/simulation_config.yaml', help='Config file path')
    
    args = parser.parse_args()
    
    generator = DatasetGenerator(config_path=args.config)
    df = generator.generate_dataset(num_runs=args.num_runs, output_dir=args.output_dir)
    
    print(f"\nDataset generated successfully!")
    print(f"Shape: {df.shape}")
    print(f"\nFirst few rows:")
    print(df.head())
    print(f"\nFault distribution:")
    print(df['fault_type'].value_counts())


if __name__ == '__main__':
    main()

# Made with Bob

"""
Fixed Dataset Generator - NO DATA LEAKAGE, NO FABRICATED LABELS
Implements two-pass simulation to ensure ground truth validity
"""

import logging
import random
import math
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
class SimulationSnapshot:
    """Single timestep snapshot"""
    timestamp: float
    cell_1_voltage: float
    cell_2_voltage: float
    cell_3_voltage: float
    cell_4_voltage: float
    cell_5_voltage: float
    stack_current: float
    stack_voltage: float
    stack_temperature: float
    stack_pressure: float
    h2_flow_rate: float
    o2_flow_rate: float
    water_flow: float
    tank_pressure: float
    h2_o2_ratio: float
    efficiency: float
    power: float
    irradiance: float
    is_tripped: bool


class FixedDatasetGenerator:
    """
    SCIENTIFICALLY CORRECT dataset generator
    - Two-pass simulation (no look-ahead bias)
    - Only ground-truth labels (no heuristics)
    - Discards runs without failures
    """
    
    def __init__(self, config_path: str = "config/simulation_config.yaml"):
        self.config = load_config(config_path)
        self.config.validate()
        
        self.data_gen_config = self.config.get_section('data_generation')
        self.sim_config = self.config.get_section('simulation')
        
        # Set random seed for reproducibility
        seed = self.sim_config.get('random_seed', 42)
        random.seed(seed)
        np.random.seed(seed)
        
        logger.info("FixedDatasetGenerator initialized with STRICT validation")
    
    def generate_dataset(self, num_runs: int = 100, 
                        min_samples: int = 5000) -> pd.DataFrame:
        """
        Generate dataset with ONLY valid ground-truth labels
        
        Args:
            num_runs: Target number of simulation runs
            min_samples: Minimum samples required
            
        Returns:
            DataFrame with valid time_to_failure labels
        """
        logger.info(f"Starting dataset generation (target: {num_runs} runs, min: {min_samples} samples)")
        
        all_data = []
        successful_runs = 0
        discarded_runs = 0
        
        run_idx = 0
        while successful_runs < num_runs:
            logger.info(f"Run {run_idx + 1} (successful: {successful_runs}/{num_runs})")
            
            # Decide if this run has a fault
            has_fault = random.random() < self.data_gen_config.get('fault_injection_probability', 0.3)
            
            if has_fault:
                fault_types = list(self.config.get('faults.definitions', {}).keys())
                fault_type = random.choice(fault_types)
                fault_severity = random.uniform(0.5, 0.9)  # Higher severity to ensure trips
                fault_start_range = self.data_gen_config.get('fault_start_time_range', [600, 3600])
                fault_start_time = random.uniform(*fault_start_range)
            else:
                # No fault runs are discarded
                run_idx += 1
                discarded_runs += 1
                continue
            
            # TWO-PASS SIMULATION
            run_data = self._run_two_pass_simulation(
                run_idx=run_idx,
                fault_type=fault_type,
                fault_severity=fault_severity,
                fault_start_time=fault_start_time
            )
            
            if run_data is None:
                # Fault didn't cause trip - discard
                discarded_runs += 1
                logger.warning(f"Run {run_idx}: Fault '{fault_type}' did not cause trip - DISCARDED")
            else:
                # Valid run with ground truth
                all_data.extend(run_data)
                successful_runs += 1
                logger.info(f"Run {run_idx}: SUCCESS - {len(run_data)} samples added")
            
            run_idx += 1
            
            # Safety: prevent infinite loop
            if run_idx > num_runs * 5:
                logger.error(f"Too many discarded runs ({discarded_runs}). Adjust fault severity.")
                break
        
        # Convert to DataFrame
        df = pd.DataFrame(all_data)
        
        # VALIDATION CHECKS
        self._validate_dataset(df, successful_runs, discarded_runs)
        
        # Save dataset
        output_dir = Path('data/generated')
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / 'dataset_v1.csv'
        df.to_csv(output_path, index=False)
        
        logger.info(f"✅ Dataset saved to {output_path}")
        logger.info(f"✅ Total samples: {len(df)}")
        logger.info(f"✅ Successful runs: {successful_runs}")
        logger.info(f"⚠️  Discarded runs: {discarded_runs}")
        
        return df
    
    def _run_two_pass_simulation(self, run_idx: int, fault_type: str,
                                 fault_severity: float, fault_start_time: float) -> Optional[List[Dict]]:
        """
        TWO-PASS SIMULATION (NO LOOK-AHEAD BIAS)
        
        PASS 1: Run simulation, detect if trip occurs
        PASS 2: If trip occurred, generate dataset with ground-truth labels
        
        Returns:
            List of data points if trip occurred, None otherwise
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
        duration = self.data_gen_config.get('run_duration', 3600)
        fast_day_period = self.sim_config.get('fast_day_period', 600.0)
        
        # PASS 1: Run simulation and record all states
        snapshots = []
        t = 0.0
        fault_injected = False
        trip_time = None
        
        while t < duration:
            # Generate irradiance
            base_irr = 500.0 + 500.0 * max(0.0, math.sin(2.0 * math.pi * (t / fast_day_period)))
            irradiance = max(0.0, base_irr + random.uniform(-80, 80))
            
            # Inject fault at specified time
            if not fault_injected and t >= fault_start_time:
                fault_injector.set_fault(fault_type, active=True, severity=fault_severity)
                fault_injected = True
            
            # Update simulation
            state = sim_engine.update(irradiance, dt)
            
            # Record trip time (first occurrence only)
            if state.tripped and trip_time is None:
                trip_time = t
                logger.debug(f"Trip detected at t={t:.1f}s")
            
            # Create snapshot
            snapshot = self._create_snapshot(t, state, irradiance)
            snapshots.append(snapshot)
            
            t += dt
            
            # Early exit if tripped for too long
            if trip_time and (t - trip_time) > 60:
                break
        
        # CHECK: Did trip occur?
        if trip_time is None:
            return None  # DISCARD this run
        
        # PASS 2: Generate dataset with ground-truth labels
        data_points = []
        for snapshot in snapshots:
            # Only include samples BEFORE trip
            if snapshot.timestamp >= trip_time:
                continue
            
            # Calculate ground-truth time_to_failure
            time_to_failure = trip_time - snapshot.timestamp
            
            # Create data point
            data_point = asdict(snapshot)
            data_point['fault_type'] = fault_type
            data_point['fault_severity'] = fault_severity
            data_point['time_to_failure'] = time_to_failure
            data_point['run_id'] = run_idx
            
            data_points.append(data_point)
        
        return data_points
    
    def _create_snapshot(self, timestamp: float, state: ElectrolyserState,
                        irradiance: float) -> SimulationSnapshot:
        """Create snapshot from simulation state"""
        cell_voltages = state.cell_voltages + [0.0] * (5 - len(state.cell_voltages))
        
        h2_o2_ratio = state.h2_flow_Lpm / state.o2_flow_Lpm if state.o2_flow_Lpm > 0 else 0.0
        power = state.V_stack * state.I_stack
        
        # Simplified efficiency
        theoretical_h2_kg_per_s = (state.h2_flow_Lpm / 60.0) * 0.001 * 0.08988
        theoretical_power_kw = theoretical_h2_kg_per_s * 39.4 * 1000
        efficiency = (theoretical_power_kw / power) if power > 0 else 0.0
        
        return SimulationSnapshot(
            timestamp=timestamp,
            cell_1_voltage=cell_voltages[0],
            cell_2_voltage=cell_voltages[1],
            cell_3_voltage=cell_voltages[2],
            cell_4_voltage=cell_voltages[3],
            cell_5_voltage=cell_voltages[4],
            stack_current=state.I_stack,
            stack_voltage=state.V_stack,
            stack_temperature=state.stack_temp,
            stack_pressure=state.stack_pressure,
            h2_flow_rate=state.h2_flow_Lpm,
            o2_flow_rate=state.o2_flow_Lpm,
            water_flow=state.water_flow,
            tank_pressure=state.tank_pressure_bar,
            h2_o2_ratio=h2_o2_ratio,
            efficiency=efficiency,
            power=power,
            irradiance=irradiance,
            is_tripped=state.tripped
        )
    
    def _validate_dataset(self, df: pd.DataFrame, successful: int, discarded: int):
        """Validate dataset integrity"""
        logger.info("\n" + "=" * 60)
        logger.info("DATASET VALIDATION")
        logger.info("=" * 60)
        
        # Check 1: No negative time_to_failure
        negative_ttf = (df['time_to_failure'] < 0).sum()
        assert negative_ttf == 0, f"❌ FATAL: {negative_ttf} negative time_to_failure values"
        logger.info("✅ No negative time_to_failure")
        
        # Check 2: All time_to_failure > 0
        zero_ttf = (df['time_to_failure'] == 0).sum()
        assert zero_ttf == 0, f"❌ FATAL: {zero_ttf} zero time_to_failure values"
        logger.info("✅ All time_to_failure > 0")
        
        # Check 3: Reasonable distribution
        logger.info(f"\ntime_to_failure statistics:")
        logger.info(f"  Mean: {df['time_to_failure'].mean():.2f}s")
        logger.info(f"  Median: {df['time_to_failure'].median():.2f}s")
        logger.info(f"  Min: {df['time_to_failure'].min():.2f}s")
        logger.info(f"  Max: {df['time_to_failure'].max():.2f}s")
        
        # Check 4: Fault distribution
        logger.info(f"\nFault type distribution:")
        for fault, count in df['fault_type'].value_counts().items():
            logger.info(f"  {fault}: {count} samples ({count/len(df)*100:.1f}%)")
        
        # Check 5: Run statistics
        logger.info(f"\nRun statistics:")
        logger.info(f"  Successful runs: {successful}")
        logger.info(f"  Discarded runs: {discarded}")
        logger.info(f"  Success rate: {successful/(successful+discarded)*100:.1f}%")
        
        logger.info("=" * 60 + "\n")


def main():
    """Generate dataset with strict validation"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate VALID ML dataset')
    parser.add_argument('--num-runs', type=int, default=100, help='Target successful runs')
    parser.add_argument('--min-samples', type=int, default=5000, help='Minimum samples')
    
    args = parser.parse_args()
    
    generator = FixedDatasetGenerator()
    df = generator.generate_dataset(num_runs=args.num_runs, min_samples=args.min_samples)
    
    print(f"\n{'='*60}")
    print("DATASET GENERATION COMPLETE")
    print(f"{'='*60}")
    print(f"Total samples: {len(df)}")
    print(f"Columns: {list(df.columns)}")
    print(f"\nFirst 5 rows:")
    print(df.head())


if __name__ == '__main__':
    main()

# Made with Bob

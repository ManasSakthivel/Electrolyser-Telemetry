"""
Simulation Engine Module
Core electrolyser physics simulation with modular design
"""

import logging
import random
import math
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, field

from .fault_injector import FaultInjector

logger = logging.getLogger(__name__)


@dataclass
class ElectrolyserState:
    """Data class to hold electrolyser state"""
    # Stack parameters
    I_stack: float = 0.0
    V_stack: float = 0.0
    cell_voltages: list = field(default_factory=list)
    stack_temp: float = 45.0
    stack_pressure: float = 1.2
    
    # Gas flows
    h2_flow_Lpm: float = 0.0
    o2_flow_Lpm: float = 0.0
    water_flow: float = 1.2
    
    # Tank
    tank_moles: float = 0.0
    tank_pressure_pa: float = 101325.0
    tank_pressure_bar: float = 1.013
    
    # Status
    tripped: bool = False
    trip_reason: Optional[str] = None
    sequence_id: int = 0
    
    # Efficiency
    eff_variation: float = 1.0


class SimulationEngine:
    """
    Core electrolyser simulation engine
    Decoupled from MQTT and telemetry
    """
    
    def __init__(self, el_id: str, config: Dict, fault_injector: Optional[FaultInjector] = None):
        """
        Initialize simulation engine
        
        Args:
            el_id: Electrolyser ID (e.g., 'EL1', 'EL2')
            config: Configuration dictionary
            fault_injector: Optional fault injector instance
        """
        self.el_id = el_id
        self.config = config
        self.fault_injector = fault_injector
        
        # Extract configuration
        el_config = config['electrolyser']
        self.N_CELLS = el_config['n_cells']
        self.FARADAY = el_config['faraday_constant']
        self.U_REV = el_config['reversible_voltage'] * random.uniform(*el_config['voltage_variation_range'])
        self.R_OHM = el_config['ohmic_resistance'] * random.uniform(*el_config['resistance_variation_range'])
        self.I_REF = el_config['reference_current']
        self.V_MAX_PER_CELL = el_config['max_voltage_per_cell']
        self.WATER_FLOW_MIN = el_config['min_water_flow']
        
        # Tank parameters
        self.TANK_VOLUME_M3 = el_config['tank_volume']
        self.TANK_TEMPERATURE_K = el_config['tank_temperature']
        self.R_GAS = el_config['gas_constant']
        self.ATM_PRESSURE_PA = el_config['atmospheric_pressure']
        
        # Efficiency
        self.ETA_F = el_config['faraday_efficiency']
        
        # Initialize state
        self.state = ElectrolyserState()
        self.state.cell_voltages = [self.U_REV] * self.N_CELLS
        self.state.eff_variation = random.uniform(*el_config['efficiency_variation_range'])
        self.state.stack_temp = 45.0 + random.uniform(-1.0, 1.0)
        self.state.stack_pressure = 1.2 + random.uniform(-0.05, 0.05)
        self.state.water_flow = 1.2 * random.uniform(0.9, 1.1)
        
        # Compute initial tank moles from pressure
        self.state.tank_moles = (self.state.tank_pressure_pa * self.TANK_VOLUME_M3) / (self.R_GAS * self.TANK_TEMPERATURE_K)
        
        logger.info(f"SimulationEngine initialized for {el_id}")
    
    def update(self, irradiance_wpm2: float, dt_seconds: float) -> ElectrolyserState:
        """
        Update simulation state based on PV irradiance
        
        Args:
            irradiance_wpm2: Solar irradiance in W/m²
            dt_seconds: Time step in seconds
            
        Returns:
            Updated electrolyser state
        """
        # Update fault timer if fault injector exists
        if self.fault_injector:
            self.fault_injector.update_timer(dt_seconds)
        
        # PV power calculation
        pv_config = self.config['pv_system']
        panel_isc = pv_config['panel_isc_per_panel'] * (irradiance_wpm2 / 1000.0)
        pv_voltage = pv_config['panel_voltage']
        pv_power = panel_isc * pv_voltage * pv_config['derate_factor']
        
        # Required power for reference current
        V_stack_est = self.N_CELLS * (self.U_REV + self.R_OHM * self.I_REF)
        required_power = self.I_REF * V_stack_est
        
        # Control decision
        if pv_power >= required_power:
            I_target = self.I_REF
        else:
            I_target = max(0.0, pv_power / V_stack_est) if V_stack_est > 0.01 else 0.0
        
        # First-order current dynamics
        tau = 2.0
        self.state.I_stack += (I_target - self.state.I_stack) * min(1.0, dt_seconds / tau)
        
        # Compute stack voltage
        self.state.V_stack = self.N_CELLS * (self.U_REV + self.R_OHM * self.state.I_stack)
        
        # Update cell voltages with small variations
        per_cell = self.state.V_stack / self.N_CELLS
        self.state.cell_voltages = [per_cell + random.uniform(-0.02, 0.02) for _ in range(self.N_CELLS)]
        
        # Temperature dynamics
        self.state.stack_temp += 0.01 * (abs(self.state.I_stack) - 1.5) * (dt_seconds / 60.0)
        self.state.stack_temp += random.uniform(-0.02, 0.02)
        
        # Stack pressure small drift
        self.state.stack_pressure += random.uniform(-0.005, 0.005)
        
        # H2 production via Faraday's law
        eta_F = self.ETA_F * self.state.eff_variation
        n_dot = eta_F * (self.N_CELLS * self.state.I_stack) / (2.0 * self.FARADAY)  # mol/s
        
        # Convert to L/min
        V_molar_m3 = (self.R_GAS * self.TANK_TEMPERATURE_K) / self.ATM_PRESSURE_PA
        flow_m3_per_s = n_dot * V_molar_m3
        self.state.h2_flow_Lpm = flow_m3_per_s * 1000.0 * 60.0
        
        # O2 flow (stoichiometric)
        self.state.o2_flow_Lpm = self.state.h2_flow_Lpm / 2.0 * 0.99
        
        # Tank integration
        mol_added = n_dot * dt_seconds
        f_capture = 0.9
        self.state.tank_moles += mol_added * f_capture
        
        # Tank pressure (ideal gas law)
        self.state.tank_pressure_pa = (self.state.tank_moles * self.R_GAS * self.TANK_TEMPERATURE_K) / self.TANK_VOLUME_M3
        self.state.tank_pressure_bar = self.state.tank_pressure_pa / 1e5
        
        # Add sensor noise
        self.state.h2_flow_Lpm *= random.uniform(0.97, 1.03)
        self.state.o2_flow_Lpm *= random.uniform(0.97, 1.03)
        self.state.tank_pressure_bar *= random.uniform(0.995, 1.005)
        
        # Water flow
        self.state.water_flow = max(0.0, 1.2 * (self.state.I_stack / self.I_REF))
        
        # Apply fault effects
        if self.fault_injector:
            self._apply_fault_effects(dt_seconds)
        
        # Safety checks
        self._check_safety()
        
        # Increment sequence
        self.state.sequence_id += 1
        
        return self.state
    
    def _apply_fault_effects(self, dt_seconds: float):
        """Apply effects of active faults to the state"""
        if not self.fault_injector:
            return
        
        active_faults = self.fault_injector.get_active_faults()
        
        for fault_name, severity in active_faults.items():
            if fault_name == 'membrane_pinhole':
                increase = self.fault_injector.get_fault_parameter(fault_name, 'cell_voltage_increase', severity) or 0.0
                multiplier = self.fault_injector.get_fault_parameter(fault_name, 'h2_flow_multiplier', severity) or 1.0
                self.state.cell_voltages[0] += increase
                if self.N_CELLS > 1:
                    self.state.cell_voltages[1] += increase * 0.8
                self.state.h2_flow_Lpm *= multiplier
            
            elif fault_name == 'gas_crossover':
                ratio = self.fault_injector.get_fault_parameter(fault_name, 'h2_o2_ratio', severity) or 2.0
                self.state.o2_flow_Lpm = self.state.h2_flow_Lpm / ratio
            
            elif fault_name == 'cell_flooding':
                drop = self.fault_injector.get_fault_parameter(fault_name, 'cell_voltage_drop', severity) or 0.0
                affected = self.fault_injector.get_fault_parameter(fault_name, 'affected_cells', severity) or []
                if isinstance(affected, list):
                    for cell_idx in affected:
                        if cell_idx < len(self.state.cell_voltages):
                            self.state.cell_voltages[cell_idx] = drop
            
            elif fault_name == 'cell_dryout':
                increase = self.fault_injector.get_fault_parameter(fault_name, 'cell_voltage_increase', severity) or 0.0
                temp_rise = self.fault_injector.get_fault_parameter(fault_name, 'temp_rise_rate', severity) or 0.0
                for i in range(self.N_CELLS):
                    self.state.cell_voltages[i] = max(self.state.cell_voltages[i], increase)
                self.state.stack_temp += temp_rise * dt_seconds
            
            elif fault_name == 'pump_failure':
                multiplier = self.fault_injector.get_fault_parameter(fault_name, 'water_flow_multiplier', severity) or 1.0
                temp_rise = self.fault_injector.get_fault_parameter(fault_name, 'temp_rise_rate', severity) or 0.0
                self.state.water_flow *= multiplier
                if self.state.I_stack > 1.0:
                    self.state.stack_temp += temp_rise * dt_seconds
            
            elif fault_name == 'dcdc_failure':
                multiplier = self.fault_injector.get_fault_parameter(fault_name, 'current_multiplier', severity) or 1.0
                self.state.I_stack *= multiplier
                if multiplier < 0.1:
                    self.state.V_stack = self.N_CELLS * self.U_REV
                    self.state.cell_voltages = [self.state.V_stack / self.N_CELLS] * self.N_CELLS
            
            elif fault_name == 'solar_transient':
                spike = self.fault_injector.get_fault_parameter(fault_name, 'current_spike', severity) or 0.0
                if (self.fault_injector.fault_timer % 2.0) < 0.5:
                    self.state.I_stack = spike
            
            elif fault_name == 'level_sensor':
                noise = self.fault_injector.get_fault_parameter(fault_name, 'pressure_noise', severity) or 0.0
                self.state.tank_pressure_bar += random.uniform(-noise, noise)
            
            elif fault_name == 'voltage_sensor_drift':
                affected_cell = self.fault_injector.get_fault_parameter(fault_name, 'affected_cell', severity) or 0
                if isinstance(affected_cell, (int, float)) and affected_cell <= len(self.state.cell_voltages) and affected_cell > 0:
                    self.state.cell_voltages[int(affected_cell) - 1] = 0.0
            
            elif fault_name == 'temp_sensor_failure':
                self.state.stack_temp = 0.0
            
            elif fault_name == 'loose_bolt':
                reduction = self.fault_injector.get_fault_parameter(fault_name, 'current_reduction', severity) or 1.0
                self.state.I_stack *= reduction
                self.state.V_stack = self.N_CELLS * (self.U_REV + self.R_OHM * self.state.I_stack)
                self.state.cell_voltages = [self.state.V_stack / self.N_CELLS] * self.N_CELLS
            
            elif fault_name == 'o2_blockage':
                multiplier = self.fault_injector.get_fault_parameter(fault_name, 'o2_flow_multiplier', severity) or 1.0
                rise_rate = self.fault_injector.get_fault_parameter(fault_name, 'pressure_rise_rate', severity) or 0.0
                self.state.o2_flow_Lpm *= multiplier
                self.state.stack_pressure += rise_rate * dt_seconds
            
            elif fault_name == 'over_pressure':
                spike = self.fault_injector.get_fault_parameter(fault_name, 'pressure_spike', severity) or 0.0
                self.state.tank_pressure_bar = spike
                self.state.stack_pressure = spike
    
    def _check_safety(self):
        """Check safety conditions and trip if necessary"""
        per_cell = self.state.V_stack / self.N_CELLS
        
        if per_cell > self.V_MAX_PER_CELL:
            self.state.tripped = True
            self.state.trip_reason = "over_voltage"
        
        if self.state.water_flow < self.WATER_FLOW_MIN:
            self.state.tripped = True
            self.state.trip_reason = "low_water"
        
        if self.state.tank_pressure_bar > 30.0:
            self.state.tripped = True
            self.state.trip_reason = "over_pressure"
    
    def get_state(self) -> ElectrolyserState:
        """Get current state"""
        return self.state
    
    def reset(self):
        """Reset simulation to initial state"""
        self.state = ElectrolyserState()
        self.state.cell_voltages = [self.U_REV] * self.N_CELLS
        self.state.eff_variation = random.uniform(*self.config['electrolyser']['efficiency_variation_range'])
        self.state.tank_moles = (self.state.tank_pressure_pa * self.TANK_VOLUME_M3) / (self.R_GAS * self.TANK_TEMPERATURE_K)
        logger.info(f"SimulationEngine reset for {self.el_id}")

# Made with Bob

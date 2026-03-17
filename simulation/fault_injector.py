"""
Fault Injector Module
Manages fault injection with configurable severity levels
"""

import logging
import random
from typing import Dict, Set, Optional, Tuple
from threading import Lock

logger = logging.getLogger(__name__)


class FaultInjector:
    """
    Manages fault injection for electrolyser simulation
    Supports multiple fault types with severity levels
    """
    
    def __init__(self, config: Dict):
        """
        Initialize fault injector with configuration
        
        Args:
            config: Fault configuration dictionary from YAML
        """
        self.config = config
        self.active_faults: Dict[int, float] = {}  # fault_id -> severity
        self.lock = Lock()
        self.fault_timer = 0.0
        
        # Build fault name to ID mapping
        self.fault_name_to_id = {}
        self.fault_id_to_name = {}
        for name, fault_config in config.items():
            fault_id = fault_config['id']
            self.fault_name_to_id[name] = fault_id
            self.fault_id_to_name[fault_id] = name
        
        logger.info(f"FaultInjector initialized with {len(self.fault_name_to_id)} fault types")
    
    def set_fault(self, fault_name: str, active: bool = True, severity: float = 0.5):
        """
        Activate or deactivate a fault
        
        Args:
            fault_name: Name of the fault (e.g., 'membrane_pinhole')
            active: Whether to activate (True) or deactivate (False)
            severity: Severity level (0.0 to 1.0), maps to severity_levels in config
        """
        fault_id = self.fault_name_to_id.get(fault_name)
        if fault_id is None:
            logger.warning(f"Unknown fault: {fault_name}")
            return
        
        with self.lock:
            if active:
                self.active_faults[fault_id] = severity
                logger.info(f"Fault activated: {fault_name} (severity: {severity:.2f})")
            else:
                self.active_faults.pop(fault_id, None)
                logger.info(f"Fault cleared: {fault_name}")
    
    def is_active(self, fault_id: int) -> bool:
        """Check if a fault is currently active"""
        with self.lock:
            return fault_id in self.active_faults
    
    def get_severity(self, fault_id: int) -> float:
        """Get severity level of active fault (0.0 if not active)"""
        with self.lock:
            return self.active_faults.get(fault_id, 0.0)
    
    def get_active_faults(self) -> Dict[str, float]:
        """Get all active faults with their severities"""
        with self.lock:
            return {
                self.fault_id_to_name[fid]: severity 
                for fid, severity in self.active_faults.items()
            }
    
    def clear_all(self):
        """Clear all active faults"""
        with self.lock:
            self.active_faults.clear()
            logger.info("All faults cleared")
    
    def update_timer(self, dt: float):
        """Update internal timer for time-based fault effects"""
        self.fault_timer += dt
    
    def get_fault_parameter(self, fault_name: str, param_name: str, severity: float):
        """
        Get fault parameter value based on severity
        
        Args:
            fault_name: Name of the fault
            param_name: Parameter name (e.g., 'cell_voltage_increase')
            severity: Severity level (0.0 to 1.0)
            
        Returns:
            Interpolated parameter value based on severity
        """
        fault_config = self.config.get(fault_name)
        if not fault_config:
            return None
        
        param_values = fault_config.get(param_name)
        if not param_values:
            return None
        
        # If single value, return it
        if not isinstance(param_values, list):
            return param_values
        
        # Interpolate based on severity
        # severity_levels: [0.3, 0.5, 0.8] maps to param_values
        severity_levels = fault_config.get('severity_levels', [0.3, 0.5, 0.8])
        
        if severity <= severity_levels[0]:
            return param_values[0]
        elif severity >= severity_levels[-1]:
            return param_values[-1]
        else:
            # Linear interpolation
            for i in range(len(severity_levels) - 1):
                if severity_levels[i] <= severity <= severity_levels[i + 1]:
                    t = (severity - severity_levels[i]) / (severity_levels[i + 1] - severity_levels[i])
                    return param_values[i] + t * (param_values[i + 1] - param_values[i])
        
        return param_values[0]
    
    def inject_random_fault(self, fault_types: Optional[list] = None, 
                           severity_range: Tuple[float, float] = (0.3, 0.8)):
        """
        Inject a random fault for testing
        
        Args:
            fault_types: List of fault names to choose from (None = all)
            severity_range: Range of severity values to sample from
        """
        if fault_types is None:
            fault_types = list(self.fault_name_to_id.keys())
        
        fault_name = random.choice(fault_types)
        severity = random.uniform(*severity_range)
        self.set_fault(fault_name, active=True, severity=severity)
        
        return fault_name, severity

# Made with Bob

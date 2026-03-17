"""
Configuration Loader
Loads and validates YAML configuration files
"""

import yaml
import logging
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)


class ConfigLoader:
    """Load and manage configuration from YAML files"""
    
    def __init__(self, config_path: str = "config/simulation_config.yaml"):
        self.config_path = Path(config_path)
        self.config = self._load_config()
        
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file"""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")
        
        with open(self.config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        logger.info(f"Configuration loaded from {self.config_path}")
        return config
    
    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Get configuration value using dot notation
        Example: config.get('simulation.timestep')
        """
        keys = key_path.split('.')
        value = self.config
        
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        
        return value
    
    def get_section(self, section: str) -> Dict[str, Any]:
        """Get entire configuration section"""
        return self.config.get(section, {})
    
    def validate(self) -> bool:
        """Validate required configuration keys"""
        required_sections = ['simulation', 'electrolyser', 'mqtt', 'faults', 'ml']
        
        for section in required_sections:
            if section not in self.config:
                logger.error(f"Missing required configuration section: {section}")
                return False
        
        logger.info("Configuration validation passed")
        return True


def load_config(config_path: str = "config/simulation_config.yaml") -> ConfigLoader:
    """Convenience function to load configuration"""
    return ConfigLoader(config_path)

# Made with Bob

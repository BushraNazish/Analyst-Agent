"""
Configuration Loader for YAML-based Configuration

This module provides a centralized configuration management system
that loads settings from config/agent_config.yaml and provides
an interface similar to os.getenv() for backward compatibility.
"""

import os
import yaml
from typing import Any, Optional
from pathlib import Path


class ConfigLoader:
    """Singleton configuration loader for YAML config files."""
    
    _instance = None
    _config = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigLoader, cls).__new__(cls)
            cls._instance._load_config()
        return cls._instance
    
    def _load_config(self) -> None:
        """Load configuration from YAML file."""
        config_path = Path(__file__).parent / "agent_config.yaml"
        
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                self._config = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            raise ValueError(f"Error parsing YAML configuration: {e}")
        
        # Set environment variables for libraries that expect them
        # This ensures backward compatibility with libraries that use os.environ
        self._set_environment_variables()
    
    def _set_environment_variables(self) -> None:
        """Set environment variables from config for backward compatibility."""
        if not self._config:
            return
        
        # Only set if not already set (don't override existing env vars)
        for key, value in self._config.items():
            if isinstance(value, (str, int, float, bool)):
                os.environ.setdefault(str(key), str(value))
    
    def get(self, key: str, default: Optional[Any] = None) -> Any:
        """
        Get configuration value by key.
        
        Args:
            key: Configuration key
            default: Default value if key not found
            
        Returns:
            Configuration value or default
        """
        return self._config.get(key, default)
    
    def get_all(self) -> dict:
        """
        Get all configuration values.
        
        Returns:
            Dictionary of all configuration values
        """
        return self._config.copy() if self._config else {}
    
    def reload(self) -> None:
        """Reload configuration from file."""
        self._load_config()


# Global instance for easy access
_config_loader = None


def get_config(key: str, default: Optional[Any] = None) -> Any:
    """
    Get configuration value by key (similar to os.getenv).
    
    Args:
        key: Configuration key
        default: Default value if key not found
        
    Returns:
        Configuration value or default
        
    Example:
        >>> api_key = get_config("OPENAI_API_KEY")
        >>> log_level = get_config("logging_level", "ERROR")
    """
    global _config_loader
    if _config_loader is None:
        _config_loader = ConfigLoader()
    return _config_loader.get(key, default)


def reload_config() -> None:
    """Reload configuration from file."""
    global _config_loader
    if _config_loader is None:
        _config_loader = ConfigLoader()
    else:
        _config_loader.reload()


def get_all_config() -> dict:
    """Get all configuration values."""
    global _config_loader
    if _config_loader is None:
        _config_loader = ConfigLoader()
    return _config_loader.get_all()


# Auto-load configuration on module import
_config_loader = ConfigLoader()

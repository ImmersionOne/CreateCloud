"""Configuration management for Crat8Cloud."""

import json
import logging
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# Default paths
DEFAULT_CONFIG_DIR = Path.home() / ".crat8cloud"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.json"
DEFAULT_CREDENTIALS_FILE = DEFAULT_CONFIG_DIR / "credentials.json"
DEFAULT_DB_FILE = DEFAULT_CONFIG_DIR / "library.db"


class AWSConfig(BaseModel):
    """AWS configuration."""

    region: str = "us-east-1"
    bucket_name: Optional[str] = None
    user_pool_id: Optional[str] = None
    client_id: Optional[str] = None


class SyncConfig(BaseModel):
    """Sync configuration."""

    auto_backup: bool = True
    backup_on_change: bool = True
    backup_schedule: str = "daily"  # "realtime", "hourly", "daily"
    scan_interval_minutes: int = 60
    max_concurrent_uploads: int = 3


class UIConfig(BaseModel):
    """UI configuration."""

    start_minimized: bool = False
    show_notifications: bool = True
    theme: str = "system"  # "light", "dark", "system"


class Crat8CloudConfig(BaseSettings):
    """Main Crat8Cloud configuration."""

    model_config = SettingsConfigDict(
        env_prefix="CRAT8CLOUD_",
        env_nested_delimiter="__",
    )

    # Paths
    music_paths: list[str] = Field(default_factory=lambda: [str(Path.home() / "Music")])
    serato_path: str = str(Path.home() / "Music" / "_Serato_")
    config_dir: str = str(DEFAULT_CONFIG_DIR)

    # User info (set after login)
    user_id: Optional[str] = None
    user_email: Optional[str] = None

    # Sub-configs
    aws: AWSConfig = Field(default_factory=AWSConfig)
    sync: SyncConfig = Field(default_factory=SyncConfig)
    ui: UIConfig = Field(default_factory=UIConfig)

    @property
    def music_paths_as_paths(self) -> list[Path]:
        """Get music paths as Path objects."""
        return [Path(p).expanduser() for p in self.music_paths]

    @property
    def serato_path_as_path(self) -> Path:
        """Get Serato path as Path object."""
        return Path(self.serato_path).expanduser()

    @property
    def config_dir_as_path(self) -> Path:
        """Get config dir as Path object."""
        return Path(self.config_dir).expanduser()

    @property
    def db_path(self) -> Path:
        """Get database file path."""
        return self.config_dir_as_path / "library.db"


class ConfigManager:
    """Manager for loading and saving configuration."""

    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize the config manager.

        Args:
            config_path: Path to config file.
        """
        self.config_path = config_path or DEFAULT_CONFIG_FILE
        self._config: Optional[Crat8CloudConfig] = None

    @property
    def config(self) -> Crat8CloudConfig:
        """Get the current configuration, loading if needed."""
        if self._config is None:
            self._config = self.load()
        return self._config

    def load(self) -> Crat8CloudConfig:
        """
        Load configuration from file.

        Returns:
            Loaded configuration.
        """
        if self.config_path.exists():
            try:
                with open(self.config_path) as f:
                    data = json.load(f)
                self._config = Crat8CloudConfig(**data)
                logger.info(f"Loaded config from {self.config_path}")
            except Exception as e:
                logger.warning(f"Failed to load config: {e}, using defaults")
                self._config = Crat8CloudConfig()
        else:
            logger.info("No config file found, using defaults")
            self._config = Crat8CloudConfig()

        return self._config

    def save(self, config: Optional[Crat8CloudConfig] = None):
        """
        Save configuration to file.

        Args:
            config: Configuration to save. Uses current if not provided.
        """
        config = config or self._config or Crat8CloudConfig()

        # Ensure config directory exists
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        # Save as JSON
        with open(self.config_path, "w") as f:
            json.dump(config.model_dump(), f, indent=2)

        logger.info(f"Saved config to {self.config_path}")
        self._config = config

    def update(self, **kwargs):
        """
        Update configuration with new values.

        Args:
            **kwargs: Configuration values to update.
        """
        current = self.config.model_dump()

        # Deep merge
        for key, value in kwargs.items():
            if isinstance(value, dict) and key in current and isinstance(current[key], dict):
                current[key].update(value)
            else:
                current[key] = value

        self._config = Crat8CloudConfig(**current)
        self.save()

    def reset(self):
        """Reset configuration to defaults."""
        self._config = Crat8CloudConfig()
        self.save()


class CredentialsManager:
    """Manager for secure credential storage."""

    def __init__(self, credentials_path: Optional[Path] = None):
        """
        Initialize the credentials manager.

        Args:
            credentials_path: Path to credentials file (fallback if keyring unavailable).
        """
        self.credentials_path = credentials_path or DEFAULT_CREDENTIALS_FILE
        self._keyring_available = self._check_keyring()

    def _check_keyring(self) -> bool:
        """Check if keyring is available."""
        try:
            import keyring
            # Try a test operation
            keyring.get_keyring()
            return True
        except Exception:
            return False

    def store_credentials(self, access_token: str, refresh_token: str, user_id: str):
        """
        Store authentication credentials securely.

        Args:
            access_token: Access token.
            refresh_token: Refresh token.
            user_id: User ID.
        """
        if self._keyring_available:
            try:
                import keyring
                keyring.set_password("crat8cloud", "access_token", access_token)
                keyring.set_password("crat8cloud", "refresh_token", refresh_token)
                keyring.set_password("crat8cloud", "user_id", user_id)
                logger.info("Stored credentials in keyring")
                return
            except Exception as e:
                logger.warning(f"Keyring storage failed: {e}")

        # Fallback to file storage
        self.credentials_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.credentials_path, "w") as f:
            json.dump({
                "access_token": access_token,
                "refresh_token": refresh_token,
                "user_id": user_id,
            }, f)
        # Set restrictive permissions
        self.credentials_path.chmod(0o600)
        logger.info("Stored credentials in file (keyring unavailable)")

    def get_credentials(self) -> Optional[dict]:
        """
        Retrieve stored credentials.

        Returns:
            Dict with access_token, refresh_token, user_id or None.
        """
        if self._keyring_available:
            try:
                import keyring
                access_token = keyring.get_password("crat8cloud", "access_token")
                refresh_token = keyring.get_password("crat8cloud", "refresh_token")
                user_id = keyring.get_password("crat8cloud", "user_id")

                if access_token and refresh_token and user_id:
                    return {
                        "access_token": access_token,
                        "refresh_token": refresh_token,
                        "user_id": user_id,
                    }
            except Exception as e:
                logger.warning(f"Keyring retrieval failed: {e}")

        # Fallback to file
        if self.credentials_path.exists():
            try:
                with open(self.credentials_path) as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Credentials file read failed: {e}")

        return None

    def clear_credentials(self):
        """Clear stored credentials."""
        if self._keyring_available:
            try:
                import keyring
                keyring.delete_password("crat8cloud", "access_token")
                keyring.delete_password("crat8cloud", "refresh_token")
                keyring.delete_password("crat8cloud", "user_id")
            except Exception:
                pass

        if self.credentials_path.exists():
            self.credentials_path.unlink()

        logger.info("Cleared credentials")


# Global config manager instance
_config_manager: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    """Get the global config manager instance."""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager


def get_config() -> Crat8CloudConfig:
    """Get the current configuration."""
    return get_config_manager().config

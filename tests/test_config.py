"""Tests for configuration management."""

import json
from pathlib import Path

import pytest

from cratecloud.config import (
    AWSConfig,
    ConfigManager,
    CrateCloudConfig,
    CredentialsManager,
    SyncConfig,
    UIConfig,
)


class TestCrateCloudConfig:
    """Tests for CrateCloudConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = CrateCloudConfig()

        assert str(Path.home() / "Music") in config.music_paths
        assert config.serato_path == str(Path.home() / "Music" / "_Serato_")
        assert config.aws.region == "us-east-1"
        assert config.sync.auto_backup is True
        assert config.ui.show_notifications is True

    def test_music_paths_as_paths(self):
        """Test converting music paths to Path objects."""
        config = CrateCloudConfig(music_paths=["~/Music", "/external/Music"])

        paths = config.music_paths_as_paths
        assert len(paths) == 2
        assert all(isinstance(p, Path) for p in paths)

    def test_custom_config(self):
        """Test custom configuration."""
        config = CrateCloudConfig(
            music_paths=["/custom/music"],
            aws=AWSConfig(region="eu-west-1", bucket_name="my-bucket"),
            sync=SyncConfig(auto_backup=False, backup_schedule="hourly"),
        )

        assert config.music_paths == ["/custom/music"]
        assert config.aws.region == "eu-west-1"
        assert config.aws.bucket_name == "my-bucket"
        assert config.sync.auto_backup is False
        assert config.sync.backup_schedule == "hourly"


class TestConfigManager:
    """Tests for ConfigManager."""

    def test_load_default_when_no_file(self, tmp_path):
        """Test loading defaults when config file doesn't exist."""
        config_path = tmp_path / "config.json"
        manager = ConfigManager(config_path=config_path)

        config = manager.load()

        assert config is not None
        assert config.sync.auto_backup is True

    def test_save_and_load(self, tmp_path):
        """Test saving and loading configuration."""
        config_path = tmp_path / "config.json"
        manager = ConfigManager(config_path=config_path)

        # Modify and save
        config = CrateCloudConfig(
            music_paths=["/test/music"],
            aws=AWSConfig(bucket_name="test-bucket"),
        )
        manager.save(config)

        # Load and verify
        loaded = manager.load()
        assert loaded.music_paths == ["/test/music"]
        assert loaded.aws.bucket_name == "test-bucket"

    def test_update(self, tmp_path):
        """Test updating configuration."""
        config_path = tmp_path / "config.json"
        manager = ConfigManager(config_path=config_path)
        manager.load()

        manager.update(
            music_paths=["/new/music"],
            sync={"auto_backup": False},
        )

        config = manager.config
        assert config.music_paths == ["/new/music"]
        assert config.sync.auto_backup is False

    def test_reset(self, tmp_path):
        """Test resetting configuration."""
        config_path = tmp_path / "config.json"
        manager = ConfigManager(config_path=config_path)

        # Modify
        manager.update(music_paths=["/custom"])

        # Reset
        manager.reset()

        assert str(Path.home() / "Music") in manager.config.music_paths


class TestCredentialsManager:
    """Tests for CredentialsManager."""

    def test_store_and_get_credentials_file(self, tmp_path):
        """Test storing and retrieving credentials via file."""
        creds_path = tmp_path / "credentials.json"
        manager = CredentialsManager(credentials_path=creds_path)
        manager._keyring_available = False  # Force file storage

        manager.store_credentials(
            access_token="test_access",
            refresh_token="test_refresh",
            user_id="test_user",
        )

        creds = manager.get_credentials()

        assert creds is not None
        assert creds["access_token"] == "test_access"
        assert creds["refresh_token"] == "test_refresh"
        assert creds["user_id"] == "test_user"

    def test_clear_credentials(self, tmp_path):
        """Test clearing credentials."""
        creds_path = tmp_path / "credentials.json"
        manager = CredentialsManager(credentials_path=creds_path)
        manager._keyring_available = False

        manager.store_credentials("access", "refresh", "user")
        assert creds_path.exists()

        manager.clear_credentials()
        assert not creds_path.exists()

    def test_get_credentials_empty(self, tmp_path):
        """Test getting credentials when none exist."""
        creds_path = tmp_path / "credentials.json"
        manager = CredentialsManager(credentials_path=creds_path)
        manager._keyring_available = False

        creds = manager.get_credentials()
        assert creds is None

    def test_credentials_file_permissions(self, tmp_path):
        """Test that credentials file has restrictive permissions."""
        creds_path = tmp_path / "credentials.json"
        manager = CredentialsManager(credentials_path=creds_path)
        manager._keyring_available = False

        manager.store_credentials("access", "refresh", "user")

        # Check file permissions (should be 0o600 = owner read/write only)
        mode = creds_path.stat().st_mode & 0o777
        assert mode == 0o600

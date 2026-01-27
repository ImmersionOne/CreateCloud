"""Tests for data models."""

from pathlib import Path

import pytest

from cratecloud.core.models import (
    BeatGrid,
    Crate,
    CuePoint,
    Group,
    Loop,
    SyncState,
    SyncStatus,
    Track,
    User,
)


class TestTrack:
    """Tests for Track model."""

    def test_track_creation(self):
        """Test basic track creation."""
        track = Track(
            file_path=Path("/music/test.mp3"),
            file_hash="abc123",
            file_size=5000000,
        )

        assert track.file_path == Path("/music/test.mp3")
        assert track.file_hash == "abc123"
        assert track.file_size == 5000000
        assert track.sync_status == SyncStatus.PENDING

    def test_track_needs_sync(self):
        """Test needs_sync method."""
        track = Track(
            file_path=Path("/music/test.mp3"),
            file_hash="abc123",
            file_size=5000000,
        )

        # Pending should need sync
        track.sync_status = SyncStatus.PENDING
        assert track.needs_sync() is True

        # Modified should need sync
        track.sync_status = SyncStatus.MODIFIED
        assert track.needs_sync() is True

        # Error should need sync (retry)
        track.sync_status = SyncStatus.ERROR
        assert track.needs_sync() is True

        # Synced should not need sync
        track.sync_status = SyncStatus.SYNCED
        assert track.needs_sync() is False

    def test_track_with_metadata(self):
        """Test track with full metadata."""
        cue_points = [
            CuePoint(index=0, position_ms=1000, color="#FF0000", name="Drop"),
            CuePoint(index=1, position_ms=30000, color="#00FF00"),
        ]

        loops = [
            Loop(index=0, start_ms=5000, end_ms=9000, locked=True),
        ]

        beatgrid = BeatGrid(bpm=128.5, first_beat_ms=100, is_dynamic=False)

        track = Track(
            file_path=Path("/music/track.mp3"),
            file_hash="def456",
            file_size=10000000,
            title="Test Track",
            artist="Test Artist",
            album="Test Album",
            genre="House",
            duration_ms=180000,
            bpm=128.5,
            key="Am",
            beatgrid=beatgrid,
            cue_points=cue_points,
            loops=loops,
            color="#0000FF",
        )

        assert track.title == "Test Track"
        assert track.bpm == 128.5
        assert len(track.cue_points) == 2
        assert track.cue_points[0].name == "Drop"
        assert len(track.loops) == 1
        assert track.loops[0].locked is True
        assert track.beatgrid.bpm == 128.5

    def test_track_to_dict(self):
        """Test track serialization."""
        track = Track(
            file_path=Path("/music/test.mp3"),
            file_hash="abc123",
            file_size=5000000,
            title="Test",
            bpm=120.0,
        )

        data = track.to_dict()

        assert data["file_path"] == "/music/test.mp3"
        assert data["file_hash"] == "abc123"
        assert data["title"] == "Test"
        assert data["bpm"] == 120.0
        assert data["sync_status"] == "pending"


class TestCrate:
    """Tests for Crate model."""

    def test_crate_creation(self):
        """Test basic crate creation."""
        crate = Crate(
            name="House",
            track_paths=[Path("/music/track1.mp3"), Path("/music/track2.mp3")],
        )

        assert crate.name == "House"
        assert len(crate.track_paths) == 2
        assert crate.is_smart_crate is False

    def test_subcrate(self):
        """Test subcrate with parent."""
        crate = Crate(
            name="Deep House",
            parent_crate="House",
            track_paths=[],
        )

        assert crate.name == "Deep House"
        assert crate.parent_crate == "House"


class TestSyncState:
    """Tests for SyncState model."""

    def test_sync_percentage(self):
        """Test sync percentage calculation."""
        state = SyncState(total_tracks=100, synced_tracks=75)
        assert state.sync_percentage == 75.0

    def test_sync_percentage_empty(self):
        """Test sync percentage with no tracks."""
        state = SyncState(total_tracks=0, synced_tracks=0)
        assert state.sync_percentage == 100.0


class TestUser:
    """Tests for User model."""

    def test_storage_remaining(self):
        """Test storage remaining calculation."""
        user = User(
            user_id="123",
            email="test@example.com",
            display_name="Test User",
            storage_used_bytes=1 * 1024 * 1024 * 1024,  # 1GB
            storage_limit_bytes=5 * 1024 * 1024 * 1024,  # 5GB
        )

        assert user.storage_remaining_bytes == 4 * 1024 * 1024 * 1024
        assert user.storage_percentage_used == 20.0


class TestGroup:
    """Tests for Group model."""

    def test_member_count(self):
        """Test member count includes owner."""
        group = Group(
            group_id="grp123",
            name="DJ Crew",
            owner_id="user1",
            member_ids=["user2", "user3"],
        )

        # Owner + 2 members = 3
        assert group.member_count == 3

"""Data models for CrateCloud."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional


class SyncStatus(Enum):
    """Synchronization status for a track."""

    PENDING = "pending"          # Not yet uploaded
    UPLOADING = "uploading"      # Currently uploading
    SYNCED = "synced"            # Successfully synced to cloud
    MODIFIED = "modified"        # Local changes not yet synced
    ERROR = "error"              # Upload failed
    DELETED_LOCAL = "deleted_local"  # Deleted locally, exists in cloud


@dataclass
class CuePoint:
    """A Serato cue point marker."""

    index: int                   # Cue point number (0-7 for hot cues)
    position_ms: float           # Position in milliseconds
    color: Optional[str] = None  # Hex color code
    name: Optional[str] = None   # Cue point label


@dataclass
class Loop:
    """A Serato loop marker."""

    index: int                   # Loop slot number
    start_ms: float              # Loop start in milliseconds
    end_ms: float                # Loop end in milliseconds
    color: Optional[str] = None  # Hex color code
    name: Optional[str] = None   # Loop label
    locked: bool = False         # Whether loop is locked


@dataclass
class BeatGrid:
    """Serato beatgrid information."""

    bpm: float                   # Beats per minute
    first_beat_ms: float         # Position of first beat in ms
    is_dynamic: bool = False     # Whether BPM changes throughout track


@dataclass
class Track:
    """Represents a music track with all its metadata."""

    # File information
    file_path: Path
    file_hash: str               # SHA-256 hash for deduplication
    file_size: int               # Size in bytes

    # Basic metadata
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    genre: Optional[str] = None
    duration_ms: Optional[float] = None

    # Serato-specific metadata
    bpm: Optional[float] = None
    key: Optional[str] = None    # Musical key (e.g., "Am", "G")
    beatgrid: Optional[BeatGrid] = None
    cue_points: list[CuePoint] = field(default_factory=list)
    loops: list[Loop] = field(default_factory=list)
    color: Optional[str] = None  # Track color in Serato

    # Sync metadata
    sync_status: SyncStatus = SyncStatus.PENDING
    s3_key: Optional[str] = None
    last_modified: Optional[datetime] = None
    last_synced: Optional[datetime] = None

    # Cloud identifiers
    cloud_id: Optional[str] = None
    user_id: Optional[str] = None

    def needs_sync(self) -> bool:
        """Check if this track needs to be synced to cloud."""
        return self.sync_status in (
            SyncStatus.PENDING,
            SyncStatus.MODIFIED,
            SyncStatus.ERROR,
        )

    def to_dict(self) -> dict:
        """Convert track to dictionary for JSON serialization."""
        return {
            "file_path": str(self.file_path),
            "file_hash": self.file_hash,
            "file_size": self.file_size,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "genre": self.genre,
            "duration_ms": self.duration_ms,
            "bpm": self.bpm,
            "key": self.key,
            "cue_points": [
                {"index": cp.index, "position_ms": cp.position_ms, "color": cp.color, "name": cp.name}
                for cp in self.cue_points
            ],
            "loops": [
                {"index": lp.index, "start_ms": lp.start_ms, "end_ms": lp.end_ms, "color": lp.color, "name": lp.name, "locked": lp.locked}
                for lp in self.loops
            ],
            "color": self.color,
            "sync_status": self.sync_status.value,
            "s3_key": self.s3_key,
            "last_modified": self.last_modified.isoformat() if self.last_modified else None,
            "last_synced": self.last_synced.isoformat() if self.last_synced else None,
            "cloud_id": self.cloud_id,
            "user_id": self.user_id,
        }


@dataclass
class Crate:
    """A Serato crate (playlist)."""

    name: str
    track_paths: list[Path] = field(default_factory=list)
    parent_crate: Optional[str] = None  # For subcrates
    is_smart_crate: bool = False

    # Sync metadata
    sync_status: SyncStatus = SyncStatus.PENDING
    cloud_id: Optional[str] = None
    last_modified: Optional[datetime] = None
    last_synced: Optional[datetime] = None


@dataclass
class SyncState:
    """Overall sync state for the library."""

    total_tracks: int = 0
    synced_tracks: int = 0
    pending_tracks: int = 0
    error_tracks: int = 0
    total_size_bytes: int = 0
    synced_size_bytes: int = 0
    last_sync: Optional[datetime] = None
    is_syncing: bool = False
    current_file: Optional[str] = None

    @property
    def sync_percentage(self) -> float:
        """Calculate sync completion percentage."""
        if self.total_tracks == 0:
            return 100.0
        return (self.synced_tracks / self.total_tracks) * 100


@dataclass
class User:
    """CrateCloud user."""

    user_id: str
    email: str
    display_name: str
    storage_used_bytes: int = 0
    storage_limit_bytes: int = 5 * 1024 * 1024 * 1024  # 5GB default
    created_at: Optional[datetime] = None

    @property
    def storage_remaining_bytes(self) -> int:
        """Calculate remaining storage."""
        return max(0, self.storage_limit_bytes - self.storage_used_bytes)

    @property
    def storage_percentage_used(self) -> float:
        """Calculate storage usage percentage."""
        if self.storage_limit_bytes == 0:
            return 100.0
        return (self.storage_used_bytes / self.storage_limit_bytes) * 100


@dataclass
class Group:
    """A sharing group (crew)."""

    group_id: str
    name: str
    owner_id: str
    member_ids: list[str] = field(default_factory=list)
    invite_code: Optional[str] = None
    created_at: Optional[datetime] = None

    @property
    def member_count(self) -> int:
        """Get total member count including owner."""
        return len(self.member_ids) + 1

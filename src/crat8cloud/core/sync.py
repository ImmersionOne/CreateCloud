"""Sync engine for coordinating local and cloud state."""

import json
import logging
import sqlite3
import threading
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from queue import PriorityQueue, Queue
from typing import Optional

from crat8cloud.core.models import Crate, SyncState, SyncStatus, Track
from crat8cloud.core.serato import SeratoParser
from crat8cloud.core.watcher import ChangeType, FileChange, MusicWatcher

logger = logging.getLogger(__name__)


class LocalDatabase:
    """SQLite database for tracking local library state."""

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize the local database.

        Args:
            db_path: Path to SQLite database file.
        """
        if db_path is None:
            # Default to ~/.crat8cloud/library.db
            db_path = Path.home() / ".crat8cloud" / "library.db"

        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()

        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tracks (
                    file_path TEXT PRIMARY KEY,
                    file_hash TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    title TEXT,
                    artist TEXT,
                    album TEXT,
                    genre TEXT,
                    duration_ms REAL,
                    bpm REAL,
                    key TEXT,
                    color TEXT,
                    cue_points_json TEXT,
                    loops_json TEXT,
                    beatgrid_json TEXT,
                    sync_status TEXT NOT NULL DEFAULT 'pending',
                    s3_key TEXT,
                    cloud_id TEXT,
                    last_modified TEXT,
                    last_synced TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS crates (
                    name TEXT PRIMARY KEY,
                    track_paths_json TEXT,
                    parent_crate TEXT,
                    is_smart_crate INTEGER DEFAULT 0,
                    sync_status TEXT NOT NULL DEFAULT 'pending',
                    cloud_id TEXT,
                    last_modified TEXT,
                    last_synced TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS sync_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    action TEXT NOT NULL,
                    file_path TEXT,
                    status TEXT NOT NULL,
                    error_message TEXT,
                    bytes_transferred INTEGER
                );

                CREATE INDEX IF NOT EXISTS idx_tracks_sync_status ON tracks(sync_status);
                CREATE INDEX IF NOT EXISTS idx_tracks_file_hash ON tracks(file_hash);
                CREATE INDEX IF NOT EXISTS idx_sync_history_timestamp ON sync_history(timestamp);
            """)

    def _get_conn(self) -> sqlite3.Connection:
        """Get a database connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def upsert_track(self, track: Track):
        """Insert or update a track in the database."""
        with self._lock:
            conn = self._get_conn()
            conn.execute("""
                INSERT INTO tracks (
                    file_path, file_hash, file_size, title, artist, album, genre,
                    duration_ms, bpm, key, color, cue_points_json, loops_json,
                    beatgrid_json, sync_status, s3_key, cloud_id, last_modified,
                    last_synced, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(file_path) DO UPDATE SET
                    file_hash = excluded.file_hash,
                    file_size = excluded.file_size,
                    title = excluded.title,
                    artist = excluded.artist,
                    album = excluded.album,
                    genre = excluded.genre,
                    duration_ms = excluded.duration_ms,
                    bpm = excluded.bpm,
                    key = excluded.key,
                    color = excluded.color,
                    cue_points_json = excluded.cue_points_json,
                    loops_json = excluded.loops_json,
                    beatgrid_json = excluded.beatgrid_json,
                    sync_status = excluded.sync_status,
                    s3_key = excluded.s3_key,
                    cloud_id = excluded.cloud_id,
                    last_modified = excluded.last_modified,
                    last_synced = excluded.last_synced,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                str(track.file_path),
                track.file_hash,
                track.file_size,
                track.title,
                track.artist,
                track.album,
                track.genre,
                track.duration_ms,
                track.bpm,
                track.key,
                track.color,
                json.dumps([{"index": cp.index, "position_ms": cp.position_ms, "color": cp.color, "name": cp.name} for cp in track.cue_points]),
                json.dumps([{"index": lp.index, "start_ms": lp.start_ms, "end_ms": lp.end_ms, "color": lp.color, "name": lp.name, "locked": lp.locked} for lp in track.loops]),
                json.dumps(asdict(track.beatgrid)) if track.beatgrid else None,
                track.sync_status.value,
                track.s3_key,
                track.cloud_id,
                track.last_modified.isoformat() if track.last_modified else None,
                track.last_synced.isoformat() if track.last_synced else None,
            ))
            conn.commit()

    def get_track(self, file_path: Path) -> Optional[Track]:
        """Get a track by file path."""
        with self._lock:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT * FROM tracks WHERE file_path = ?",
                (str(file_path),)
            ).fetchone()

            if row is None:
                return None

            return self._row_to_track(row)

    def get_tracks_by_status(self, status: SyncStatus) -> list[Track]:
        """Get all tracks with a given sync status."""
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM tracks WHERE sync_status = ?",
                (status.value,)
            ).fetchall()

            return [self._row_to_track(row) for row in rows]

    def get_all_tracks(self) -> list[Track]:
        """Get all tracks."""
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute("SELECT * FROM tracks").fetchall()
            return [self._row_to_track(row) for row in rows]

    def _row_to_track(self, row: sqlite3.Row) -> Track:
        """Convert a database row to a Track object."""
        from crat8cloud.core.models import BeatGrid, CuePoint, Loop

        cue_points = []
        if row["cue_points_json"]:
            for cp in json.loads(row["cue_points_json"]):
                cue_points.append(CuePoint(**cp))

        loops = []
        if row["loops_json"]:
            for lp in json.loads(row["loops_json"]):
                loops.append(Loop(**lp))

        beatgrid = None
        if row["beatgrid_json"]:
            beatgrid = BeatGrid(**json.loads(row["beatgrid_json"]))

        return Track(
            file_path=Path(row["file_path"]),
            file_hash=row["file_hash"],
            file_size=row["file_size"],
            title=row["title"],
            artist=row["artist"],
            album=row["album"],
            genre=row["genre"],
            duration_ms=row["duration_ms"],
            bpm=row["bpm"],
            key=row["key"],
            color=row["color"],
            cue_points=cue_points,
            loops=loops,
            beatgrid=beatgrid,
            sync_status=SyncStatus(row["sync_status"]),
            s3_key=row["s3_key"],
            cloud_id=row["cloud_id"],
            last_modified=datetime.fromisoformat(row["last_modified"]) if row["last_modified"] else None,
            last_synced=datetime.fromisoformat(row["last_synced"]) if row["last_synced"] else None,
        )

    def update_track_status(self, file_path: Path, status: SyncStatus, s3_key: Optional[str] = None):
        """Update a track's sync status."""
        with self._lock:
            conn = self._get_conn()
            if s3_key:
                conn.execute(
                    "UPDATE tracks SET sync_status = ?, s3_key = ?, last_synced = ?, updated_at = CURRENT_TIMESTAMP WHERE file_path = ?",
                    (status.value, s3_key, datetime.now().isoformat(), str(file_path))
                )
            else:
                conn.execute(
                    "UPDATE tracks SET sync_status = ?, updated_at = CURRENT_TIMESTAMP WHERE file_path = ?",
                    (status.value, str(file_path))
                )
            conn.commit()

    def delete_track(self, file_path: Path):
        """Delete a track from the database."""
        with self._lock:
            conn = self._get_conn()
            conn.execute("DELETE FROM tracks WHERE file_path = ?", (str(file_path),))
            conn.commit()

    def get_sync_state(self) -> SyncState:
        """Get overall sync state."""
        with self._lock:
            conn = self._get_conn()

            total = conn.execute("SELECT COUNT(*), SUM(file_size) FROM tracks").fetchone()
            synced = conn.execute(
                "SELECT COUNT(*), SUM(file_size) FROM tracks WHERE sync_status = ?",
                (SyncStatus.SYNCED.value,)
            ).fetchone()
            pending = conn.execute(
                "SELECT COUNT(*) FROM tracks WHERE sync_status IN (?, ?)",
                (SyncStatus.PENDING.value, SyncStatus.MODIFIED.value)
            ).fetchone()
            errors = conn.execute(
                "SELECT COUNT(*) FROM tracks WHERE sync_status = ?",
                (SyncStatus.ERROR.value,)
            ).fetchone()
            last_sync = conn.execute(
                "SELECT MAX(last_synced) FROM tracks WHERE last_synced IS NOT NULL"
            ).fetchone()

            return SyncState(
                total_tracks=total[0] or 0,
                synced_tracks=synced[0] or 0,
                pending_tracks=pending[0] or 0,
                error_tracks=errors[0] or 0,
                total_size_bytes=total[1] or 0,
                synced_size_bytes=synced[1] or 0,
                last_sync=datetime.fromisoformat(last_sync[0]) if last_sync[0] else None,
            )

    def close(self):
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None


class SyncEngine:
    """Engine for synchronizing local library with cloud storage."""

    def __init__(
        self,
        music_paths: Optional[list[Path]] = None,
        serato_path: Optional[Path] = None,
        db_path: Optional[Path] = None,
    ):
        """
        Initialize the sync engine.

        Args:
            music_paths: Paths to music folders.
            serato_path: Path to Serato folder.
            db_path: Path to local database.
        """
        self.music_paths = music_paths or [Path.home() / "Music"]
        self.serato_path = serato_path or Path.home() / "Music" / "_Serato_"

        self.parser = SeratoParser(serato_path=self.serato_path, music_paths=self.music_paths)
        self.db = LocalDatabase(db_path)
        self.watcher: Optional[MusicWatcher] = None

        # Upload queue (priority queue - smaller files first)
        self._upload_queue: PriorityQueue[tuple[int, Track]] = PriorityQueue()
        self._upload_thread: Optional[threading.Thread] = None
        self._running = False

        # Cloud client (will be set when authenticated)
        self._s3_client = None

    def set_s3_client(self, s3_client):
        """Set the S3 client for uploads."""
        self._s3_client = s3_client

    def scan_and_index(self, progress_callback=None):
        """
        Scan the library and index all tracks.

        Args:
            progress_callback: Optional callback(current, total, track_path) for progress.
        """
        logger.info("Starting library scan and index...")

        music_files = self.parser.get_all_music_files()
        total = len(music_files)

        for i, file_path in enumerate(music_files):
            try:
                # Check if already indexed and unchanged
                existing = self.db.get_track(file_path)
                file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)

                if existing and existing.last_modified and existing.last_modified >= file_mtime:
                    # File unchanged, skip parsing
                    logger.debug(f"Skipping unchanged file: {file_path}")
                else:
                    # Parse and index
                    track = self.parser.parse_track(file_path)

                    # Preserve sync status if already synced
                    if existing and existing.sync_status == SyncStatus.SYNCED:
                        if existing.file_hash != track.file_hash:
                            track.sync_status = SyncStatus.MODIFIED
                        else:
                            track.sync_status = SyncStatus.SYNCED
                            track.s3_key = existing.s3_key
                            track.last_synced = existing.last_synced

                    self.db.upsert_track(track)

                if progress_callback:
                    progress_callback(i + 1, total, str(file_path))

            except Exception as e:
                logger.error(f"Error indexing {file_path}: {e}")

        logger.info(f"Indexed {total} tracks")

    def start_watching(self):
        """Start watching for file changes."""
        if self.watcher:
            return

        self.watcher = MusicWatcher(
            music_paths=self.music_paths,
            serato_path=self.serato_path,
            on_change=self._handle_file_change,
        )
        self.watcher.start()

    def stop_watching(self):
        """Stop watching for file changes."""
        if self.watcher:
            self.watcher.stop()
            self.watcher = None

    def _handle_file_change(self, change: FileChange):
        """Handle a file system change."""
        logger.info(f"Handling change: {change.change_type.value} - {change.file_path}")

        if change.change_type == ChangeType.CREATED:
            # New file - parse and queue for upload
            try:
                track = self.parser.parse_track(change.file_path)
                self.db.upsert_track(track)
                self._queue_upload(track)
            except Exception as e:
                logger.error(f"Error handling new file: {e}")

        elif change.change_type == ChangeType.MODIFIED:
            # Modified file - reparse and mark for re-upload
            try:
                track = self.parser.parse_track(change.file_path)
                existing = self.db.get_track(change.file_path)

                if existing and existing.file_hash != track.file_hash:
                    track.sync_status = SyncStatus.MODIFIED

                self.db.upsert_track(track)

                if track.needs_sync():
                    self._queue_upload(track)
            except Exception as e:
                logger.error(f"Error handling modified file: {e}")

        elif change.change_type == ChangeType.DELETED:
            # Deleted file - mark as deleted
            self.db.update_track_status(change.file_path, SyncStatus.DELETED_LOCAL)

        elif change.change_type == ChangeType.MOVED:
            # Moved file - update path
            if change.old_path:
                existing = self.db.get_track(change.old_path)
                if existing:
                    self.db.delete_track(change.old_path)
                    existing.file_path = change.file_path
                    self.db.upsert_track(existing)

    def _queue_upload(self, track: Track):
        """Add a track to the upload queue."""
        # Priority is file size (smaller files first for faster progress)
        self._upload_queue.put((track.file_size, track))

    def queue_pending_uploads(self):
        """Queue all pending tracks for upload."""
        pending = self.db.get_tracks_by_status(SyncStatus.PENDING)
        modified = self.db.get_tracks_by_status(SyncStatus.MODIFIED)
        errors = self.db.get_tracks_by_status(SyncStatus.ERROR)

        for track in pending + modified + errors:
            self._queue_upload(track)

        logger.info(f"Queued {len(pending) + len(modified) + len(errors)} tracks for upload")

    def start_upload_worker(self):
        """Start the background upload worker."""
        if self._upload_thread and self._upload_thread.is_alive():
            return

        self._running = True
        self._upload_thread = threading.Thread(target=self._upload_worker, daemon=True)
        self._upload_thread.start()

    def stop_upload_worker(self):
        """Stop the upload worker."""
        self._running = False
        if self._upload_thread:
            self._upload_thread.join(timeout=5)

    def _upload_worker(self):
        """Background worker that processes the upload queue."""
        while self._running:
            try:
                # Get next track from queue (with timeout)
                _, track = self._upload_queue.get(timeout=1.0)

                if self._s3_client is None:
                    logger.warning("No S3 client configured, skipping upload")
                    continue

                self._upload_track(track)

            except Exception:
                # Queue empty or timeout
                pass

    def _upload_track(self, track: Track):
        """Upload a single track to S3."""
        if self._s3_client is None:
            return

        try:
            # Mark as uploading
            self.db.update_track_status(track.file_path, SyncStatus.UPLOADING)

            # Upload to S3
            s3_key = self._s3_client.upload_track(track)

            # Mark as synced
            self.db.update_track_status(track.file_path, SyncStatus.SYNCED, s3_key=s3_key)
            logger.info(f"Uploaded: {track.file_path}")

        except Exception as e:
            logger.error(f"Upload failed for {track.file_path}: {e}")
            self.db.update_track_status(track.file_path, SyncStatus.ERROR)

    def get_sync_state(self) -> SyncState:
        """Get the current sync state."""
        state = self.db.get_sync_state()
        state.is_syncing = self._running and not self._upload_queue.empty()
        return state

    def close(self):
        """Clean up resources."""
        self.stop_watching()
        self.stop_upload_worker()
        self.db.close()

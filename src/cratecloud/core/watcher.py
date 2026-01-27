"""File system watcher for monitoring music folder changes."""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from queue import Queue
from typing import Optional

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from cratecloud.core.serato import SUPPORTED_EXTENSIONS

logger = logging.getLogger(__name__)


class ChangeType(Enum):
    """Type of file system change."""

    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"
    MOVED = "moved"


@dataclass
class FileChange:
    """Represents a file system change event."""

    change_type: ChangeType
    file_path: Path
    old_path: Optional[Path] = None  # For moved files
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


class MusicFileHandler(FileSystemEventHandler):
    """Handler for music file system events."""

    def __init__(self, change_queue: Queue, debounce_seconds: float = 2.0):
        """
        Initialize the handler.

        Args:
            change_queue: Queue to put file changes into.
            debounce_seconds: Time to wait before processing changes (to batch rapid changes).
        """
        super().__init__()
        self.change_queue = change_queue
        self.debounce_seconds = debounce_seconds
        self._pending_changes: dict[Path, FileChange] = {}
        self._lock = threading.Lock()
        self._debounce_timer: Optional[threading.Timer] = None

    def _is_music_file(self, path: str) -> bool:
        """Check if the path is a supported music file."""
        path_obj = Path(path)

        # Check extension
        if path_obj.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return False

        # Ignore hidden files and _Serato_ folder
        if any(part.startswith(".") or part.startswith("_Serato_") for part in path_obj.parts):
            return False

        return True

    def _is_serato_file(self, path: str) -> bool:
        """Check if the path is a Serato metadata file we care about."""
        path_obj = Path(path)

        # We want to track changes to crate files
        if "_Serato_" in str(path_obj):
            if path_obj.suffix == ".crate":
                return True
            if path_obj.name == "database V2":
                return True

        return False

    def _queue_change(self, change: FileChange):
        """Queue a change with debouncing."""
        with self._lock:
            # For the same file, keep only the latest change
            # (but preserve CREATED if followed by MODIFIED)
            existing = self._pending_changes.get(change.file_path)
            if existing and existing.change_type == ChangeType.CREATED and change.change_type == ChangeType.MODIFIED:
                # Keep the CREATED event
                pass
            else:
                self._pending_changes[change.file_path] = change

            # Reset debounce timer
            if self._debounce_timer:
                self._debounce_timer.cancel()

            self._debounce_timer = threading.Timer(self.debounce_seconds, self._flush_changes)
            self._debounce_timer.start()

    def _flush_changes(self):
        """Flush pending changes to the queue."""
        with self._lock:
            for change in self._pending_changes.values():
                self.change_queue.put(change)
            self._pending_changes.clear()

    def on_created(self, event: FileSystemEvent):
        """Handle file creation."""
        if event.is_directory:
            return

        if self._is_music_file(event.src_path) or self._is_serato_file(event.src_path):
            logger.debug(f"File created: {event.src_path}")
            self._queue_change(FileChange(
                change_type=ChangeType.CREATED,
                file_path=Path(event.src_path),
            ))

    def on_modified(self, event: FileSystemEvent):
        """Handle file modification."""
        if event.is_directory:
            return

        if self._is_music_file(event.src_path) or self._is_serato_file(event.src_path):
            logger.debug(f"File modified: {event.src_path}")
            self._queue_change(FileChange(
                change_type=ChangeType.MODIFIED,
                file_path=Path(event.src_path),
            ))

    def on_deleted(self, event: FileSystemEvent):
        """Handle file deletion."""
        if event.is_directory:
            return

        if self._is_music_file(event.src_path) or self._is_serato_file(event.src_path):
            logger.debug(f"File deleted: {event.src_path}")
            self._queue_change(FileChange(
                change_type=ChangeType.DELETED,
                file_path=Path(event.src_path),
            ))

    def on_moved(self, event: FileSystemEvent):
        """Handle file move/rename."""
        if event.is_directory:
            return

        src_is_music = self._is_music_file(event.src_path)
        dest_is_music = self._is_music_file(event.dest_path)

        if src_is_music or dest_is_music:
            logger.debug(f"File moved: {event.src_path} -> {event.dest_path}")
            self._queue_change(FileChange(
                change_type=ChangeType.MOVED,
                file_path=Path(event.dest_path),
                old_path=Path(event.src_path),
            ))


class MusicWatcher:
    """Watches music folders for changes and triggers sync."""

    def __init__(
        self,
        music_paths: Optional[list[Path]] = None,
        serato_path: Optional[Path] = None,
        on_change: Optional[Callable[[FileChange], None]] = None,
    ):
        """
        Initialize the music watcher.

        Args:
            music_paths: Paths to watch for music files.
            serato_path: Path to _Serato_ folder.
            on_change: Callback function when a change is detected.
        """
        self.music_paths = music_paths or [Path.home() / "Music"]
        self.serato_path = serato_path or Path.home() / "Music" / "_Serato_"
        self.on_change = on_change

        self._change_queue: Queue[FileChange] = Queue()
        self._observer: Optional[Observer] = None
        self._processor_thread: Optional[threading.Thread] = None
        self._running = False

    def start(self):
        """Start watching for file changes."""
        if self._running:
            logger.warning("Watcher already running")
            return

        logger.info("Starting music watcher...")
        self._running = True

        # Create observer
        self._observer = Observer()
        handler = MusicFileHandler(self._change_queue)

        # Watch music paths
        for music_path in self.music_paths:
            if music_path.exists():
                logger.info(f"Watching: {music_path}")
                self._observer.schedule(handler, str(music_path), recursive=True)
            else:
                logger.warning(f"Music path does not exist: {music_path}")

        # Also watch Serato folder for crate changes
        if self.serato_path.exists():
            logger.info(f"Watching Serato folder: {self.serato_path}")
            self._observer.schedule(handler, str(self.serato_path), recursive=True)

        # Start observer
        self._observer.start()

        # Start change processor thread
        self._processor_thread = threading.Thread(target=self._process_changes, daemon=True)
        self._processor_thread.start()

        logger.info("Music watcher started")

    def stop(self):
        """Stop watching for file changes."""
        if not self._running:
            return

        logger.info("Stopping music watcher...")
        self._running = False

        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None

        logger.info("Music watcher stopped")

    def _process_changes(self):
        """Process file changes from the queue."""
        while self._running:
            try:
                # Block with timeout to allow checking _running flag
                change = self._change_queue.get(timeout=1.0)

                logger.info(f"Processing change: {change.change_type.value} - {change.file_path}")

                if self.on_change:
                    try:
                        self.on_change(change)
                    except Exception as e:
                        logger.error(f"Error in change callback: {e}")

            except Exception:
                # Queue.get timeout, continue loop
                pass

    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()


def watch_music_folder(
    music_paths: Optional[list[Path]] = None,
    on_change: Optional[Callable[[FileChange], None]] = None,
    block: bool = True,
):
    """
    Convenience function to start watching music folders.

    Args:
        music_paths: Paths to watch.
        on_change: Callback for changes.
        block: If True, block until interrupted.
    """
    watcher = MusicWatcher(music_paths=music_paths, on_change=on_change)
    watcher.start()

    if block:
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            watcher.stop()

    return watcher

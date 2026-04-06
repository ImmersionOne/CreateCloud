"""Serato metadata parsing and extraction."""

import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from crat8cloud.core.models import BeatGrid, Crate, CuePoint, Loop, SyncStatus, Track

logger = logging.getLogger(__name__)

# Supported audio file extensions
SUPPORTED_EXTENSIONS = {
    ".mp3", ".m4a", ".mp4", ".flac", ".aiff", ".aif", ".wav", ".ogg", ".alac"
}


class SeratoParser:
    """Parser for Serato library data and track metadata."""

    def __init__(self, serato_path: Optional[Path] = None, music_paths: Optional[list[Path]] = None):
        """
        Initialize the Serato parser.

        Args:
            serato_path: Path to the _Serato_ folder. Defaults to ~/Music/_Serato_
            music_paths: List of paths to scan for music files. Defaults to ~/Music
        """
        self.serato_path = serato_path or Path.home() / "Music" / "_Serato_"
        self.music_paths = music_paths or [Path.home() / "Music"]

        # Serato subfolder paths
        self.subcrates_path = self.serato_path / "Subcrates"
        self.smartcrates_path = self.serato_path / "SmartCrates"
        self.database_path = self.serato_path / "database V2"
        self.history_path = self.serato_path / "History"

    def is_serato_installed(self) -> bool:
        """Check if Serato folder exists."""
        return self.serato_path.exists()

    def get_all_music_files(self) -> list[Path]:
        """
        Scan music paths for all supported audio files.

        Returns:
            List of paths to audio files.
        """
        music_files = []

        for music_path in self.music_paths:
            if not music_path.exists():
                logger.warning(f"Music path does not exist: {music_path}")
                continue

            for ext in SUPPORTED_EXTENSIONS:
                # Use rglob for recursive search
                music_files.extend(music_path.rglob(f"*{ext}"))
                music_files.extend(music_path.rglob(f"*{ext.upper()}"))

        # Filter out hidden files and _Serato_ folder contents
        music_files = [
            f for f in music_files
            if not any(part.startswith(".") or part.startswith("_Serato_") for part in f.parts)
        ]

        return sorted(set(music_files))

    def compute_file_hash(self, file_path: Path) -> str:
        """
        Compute SHA-256 hash of a file for deduplication.

        Args:
            file_path: Path to the file.

        Returns:
            Hex-encoded SHA-256 hash.
        """
        sha256 = hashlib.sha256()

        with open(file_path, "rb") as f:
            # Read in chunks for memory efficiency
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)

        return sha256.hexdigest()

    def parse_track(self, file_path: Path) -> Track:
        """
        Parse a track file and extract all metadata including Serato data.

        Args:
            file_path: Path to the audio file.

        Returns:
            Track object with all metadata.
        """
        if not file_path.exists():
            raise FileNotFoundError(f"Track not found: {file_path}")

        # Get basic file info
        file_stat = file_path.stat()
        file_hash = self.compute_file_hash(file_path)

        # Initialize track with file info
        track = Track(
            file_path=file_path,
            file_hash=file_hash,
            file_size=file_stat.st_size,
            last_modified=datetime.fromtimestamp(file_stat.st_mtime),
            sync_status=SyncStatus.PENDING,
        )

        # Try to parse metadata using mutagen and serato-tools
        try:
            track = self._parse_audio_metadata(track)
        except Exception as e:
            logger.warning(f"Failed to parse audio metadata for {file_path}: {e}")

        try:
            track = self._parse_serato_tags(track)
        except Exception as e:
            logger.warning(f"Failed to parse Serato tags for {file_path}: {e}")

        return track

    def _parse_audio_metadata(self, track: Track) -> Track:
        """Parse basic audio metadata using mutagen."""
        try:
            from mutagen import File as MutagenFile

            audio = MutagenFile(track.file_path, easy=True)
            if audio is None:
                return track

            # Extract common tags
            track.title = self._get_tag(audio, "title")
            track.artist = self._get_tag(audio, "artist")
            track.album = self._get_tag(audio, "album")
            track.genre = self._get_tag(audio, "genre")

            # Get duration if available
            if hasattr(audio, "info") and hasattr(audio.info, "length"):
                track.duration_ms = audio.info.length * 1000

        except ImportError:
            logger.warning("mutagen not installed, skipping audio metadata parsing")
        except Exception as e:
            logger.warning(f"Error parsing audio metadata: {e}")

        return track

    def _get_tag(self, audio, tag_name: str) -> Optional[str]:
        """Safely get a tag value from mutagen audio file."""
        try:
            value = audio.get(tag_name)
            if value:
                return str(value[0]) if isinstance(value, list) else str(value)
        except (KeyError, IndexError, TypeError):
            pass
        return None

    def _parse_serato_tags(self, track: Track) -> Track:
        """Parse Serato-specific metadata from file tags."""
        try:
            # Try to use serato-tools for comprehensive parsing
            from serato_tools import SeratoTrack

            serato_track = SeratoTrack(str(track.file_path))

            # Extract BPM
            if hasattr(serato_track, "bpm") and serato_track.bpm:
                track.bpm = float(serato_track.bpm)

            # Extract key
            if hasattr(serato_track, "key") and serato_track.key:
                track.key = str(serato_track.key)

            # Extract cue points
            if hasattr(serato_track, "cues") and serato_track.cues:
                track.cue_points = [
                    CuePoint(
                        index=i,
                        position_ms=cue.position if hasattr(cue, "position") else 0,
                        color=getattr(cue, "color", None),
                        name=getattr(cue, "name", None),
                    )
                    for i, cue in enumerate(serato_track.cues)
                    if cue is not None
                ]

            # Extract loops
            if hasattr(serato_track, "loops") and serato_track.loops:
                track.loops = [
                    Loop(
                        index=i,
                        start_ms=loop.start if hasattr(loop, "start") else 0,
                        end_ms=loop.end if hasattr(loop, "end") else 0,
                        color=getattr(loop, "color", None),
                        name=getattr(loop, "name", None),
                        locked=getattr(loop, "locked", False),
                    )
                    for i, loop in enumerate(serato_track.loops)
                    if loop is not None
                ]

            # Extract track color
            if hasattr(serato_track, "color") and serato_track.color:
                track.color = str(serato_track.color)

            # Extract beatgrid
            if hasattr(serato_track, "beatgrid") and serato_track.beatgrid:
                bg = serato_track.beatgrid
                track.beatgrid = BeatGrid(
                    bpm=getattr(bg, "bpm", track.bpm or 120.0),
                    first_beat_ms=getattr(bg, "first_beat", 0),
                    is_dynamic=getattr(bg, "is_dynamic", False),
                )
                # Use beatgrid BPM if track BPM not set
                if track.bpm is None and track.beatgrid:
                    track.bpm = track.beatgrid.bpm

        except ImportError:
            logger.info("serato-tools not installed, trying fallback parsing")
            track = self._parse_serato_tags_fallback(track)
        except Exception as e:
            logger.warning(f"Error parsing Serato tags with serato-tools: {e}")
            track = self._parse_serato_tags_fallback(track)

        return track

    def _parse_serato_tags_fallback(self, track: Track) -> Track:
        """Fallback Serato tag parsing using raw ID3 GEOB tags."""
        try:
            from mutagen.id3 import ID3
            from mutagen.mp3 import MP3

            if track.file_path.suffix.lower() != ".mp3":
                return track

            audio = MP3(track.file_path)
            if audio.tags is None:
                return track

            # Look for Serato GEOB tags
            for key, value in audio.tags.items():
                if key.startswith("GEOB:Serato"):
                    # Found a Serato tag - log it for now
                    logger.debug(f"Found Serato tag: {key}")

            # Try to get BPM from standard tag
            if "TBPM" in audio.tags:
                try:
                    track.bpm = float(audio.tags["TBPM"].text[0])
                except (ValueError, IndexError):
                    pass

            # Try to get key from standard tag
            if "TKEY" in audio.tags:
                try:
                    track.key = str(audio.tags["TKEY"].text[0])
                except (ValueError, IndexError):
                    pass

        except ImportError:
            logger.warning("mutagen not installed")
        except Exception as e:
            logger.warning(f"Error in fallback Serato parsing: {e}")

        return track

    def get_crates(self) -> list[Crate]:
        """
        Parse all Serato crates.

        Returns:
            List of Crate objects.
        """
        crates = []

        if not self.subcrates_path.exists():
            logger.warning(f"Subcrates folder not found: {self.subcrates_path}")
            return crates

        # Parse each .crate file
        for crate_file in self.subcrates_path.glob("*.crate"):
            try:
                crate = self._parse_crate_file(crate_file)
                crates.append(crate)
            except Exception as e:
                logger.error(f"Failed to parse crate {crate_file}: {e}")

        return crates

    def _parse_crate_file(self, crate_file: Path) -> Crate:
        """
        Parse a single Serato crate file.

        Args:
            crate_file: Path to the .crate file.

        Returns:
            Crate object.
        """
        # Crate name is derived from filename
        # Subcrates use %% as separator (e.g., "ParentCrate%%SubCrate.crate")
        crate_name = crate_file.stem
        parent_crate = None

        if "%%" in crate_name:
            parts = crate_name.split("%%")
            crate_name = parts[-1]
            parent_crate = "%%".join(parts[:-1])

        track_paths = []

        try:
            # Try to use serato-tools for crate parsing
            from serato_tools import SeratoCrate

            serato_crate = SeratoCrate(str(crate_file))
            if hasattr(serato_crate, "tracks"):
                track_paths = [Path(t) for t in serato_crate.tracks]
        except ImportError:
            # Fallback: parse binary format manually
            track_paths = self._parse_crate_binary(crate_file)
        except Exception as e:
            logger.warning(f"Error parsing crate with serato-tools: {e}")
            track_paths = self._parse_crate_binary(crate_file)

        return Crate(
            name=crate_name,
            track_paths=track_paths,
            parent_crate=parent_crate,
            is_smart_crate=False,
            last_modified=datetime.fromtimestamp(crate_file.stat().st_mtime),
        )

    def _parse_crate_binary(self, crate_file: Path) -> list[Path]:
        """
        Parse crate file binary format manually.

        The format is a sequence of records:
        - 4 bytes: tag (ASCII)
        - 4 bytes: length (big-endian uint32)
        - N bytes: data

        Track paths are in 'otrk' records containing 'ptrk' subrecords.
        """
        track_paths = []

        try:
            with open(crate_file, "rb") as f:
                data = f.read()

            pos = 0
            while pos < len(data) - 8:
                tag = data[pos:pos+4].decode("ascii", errors="ignore")
                length = int.from_bytes(data[pos+4:pos+8], "big")

                if tag == "otrk":
                    # Parse the otrk record for ptrk
                    otrk_data = data[pos+8:pos+8+length]
                    track_path = self._extract_ptrk(otrk_data)
                    if track_path:
                        track_paths.append(track_path)

                pos += 8 + length

        except Exception as e:
            logger.error(f"Error parsing crate binary: {e}")

        return track_paths

    def _extract_ptrk(self, otrk_data: bytes) -> Optional[Path]:
        """Extract track path from otrk record data."""
        pos = 0
        while pos < len(otrk_data) - 8:
            tag = otrk_data[pos:pos+4].decode("ascii", errors="ignore")
            length = int.from_bytes(otrk_data[pos+4:pos+8], "big")

            if tag == "ptrk":
                # Path is UTF-16 encoded
                try:
                    path_str = otrk_data[pos+8:pos+8+length].decode("utf-16-be")
                    return Path(path_str)
                except UnicodeDecodeError:
                    pass

            pos += 8 + length

        return None

    def scan_library(self) -> tuple[list[Track], list[Crate]]:
        """
        Perform a full library scan.

        Returns:
            Tuple of (tracks, crates).
        """
        logger.info("Starting library scan...")

        # Get all music files
        music_files = self.get_all_music_files()
        logger.info(f"Found {len(music_files)} music files")

        # Parse each track
        tracks = []
        for i, file_path in enumerate(music_files):
            try:
                track = self.parse_track(file_path)
                tracks.append(track)

                if (i + 1) % 100 == 0:
                    logger.info(f"Parsed {i + 1}/{len(music_files)} tracks")
            except Exception as e:
                logger.error(f"Failed to parse track {file_path}: {e}")

        # Get crates
        crates = self.get_crates()
        logger.info(f"Found {len(crates)} crates")

        logger.info(f"Library scan complete: {len(tracks)} tracks, {len(crates)} crates")
        return tracks, crates

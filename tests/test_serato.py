"""Tests for Serato parser."""

import tempfile
from pathlib import Path

import pytest

from crat8cloud.core.serato import SUPPORTED_EXTENSIONS, SeratoParser


class TestSeratoParser:
    """Tests for SeratoParser."""

    def test_supported_extensions(self):
        """Test supported audio extensions."""
        assert ".mp3" in SUPPORTED_EXTENSIONS
        assert ".wav" in SUPPORTED_EXTENSIONS
        assert ".flac" in SUPPORTED_EXTENSIONS
        assert ".aiff" in SUPPORTED_EXTENSIONS
        assert ".m4a" in SUPPORTED_EXTENSIONS

    def test_parser_init_default_paths(self):
        """Test parser initializes with default paths."""
        parser = SeratoParser()

        assert parser.serato_path == Path.home() / "Music" / "_Serato_"
        assert Path.home() / "Music" in parser.music_paths

    def test_parser_init_custom_paths(self):
        """Test parser with custom paths."""
        custom_serato = Path("/custom/_Serato_")
        custom_music = [Path("/custom/music")]

        parser = SeratoParser(
            serato_path=custom_serato,
            music_paths=custom_music,
        )

        assert parser.serato_path == custom_serato
        assert parser.music_paths == custom_music

    def test_compute_file_hash(self, tmp_path):
        """Test file hash computation."""
        # Create a test file
        test_file = tmp_path / "test.txt"
        test_file.write_bytes(b"test content")

        parser = SeratoParser()
        hash1 = parser.compute_file_hash(test_file)

        # Same content should give same hash
        test_file2 = tmp_path / "test2.txt"
        test_file2.write_bytes(b"test content")
        hash2 = parser.compute_file_hash(test_file2)

        assert hash1 == hash2

        # Different content should give different hash
        test_file3 = tmp_path / "test3.txt"
        test_file3.write_bytes(b"different content")
        hash3 = parser.compute_file_hash(test_file3)

        assert hash1 != hash3

    def test_get_all_music_files_empty(self, tmp_path):
        """Test scanning empty directory."""
        parser = SeratoParser(music_paths=[tmp_path])
        files = parser.get_all_music_files()

        assert files == []

    def test_get_all_music_files(self, tmp_path):
        """Test scanning directory with music files."""
        # Create test files
        (tmp_path / "track1.mp3").touch()
        (tmp_path / "track2.wav").touch()
        (tmp_path / "track3.flac").touch()
        (tmp_path / "document.pdf").touch()  # Should be ignored
        (tmp_path / ".hidden.mp3").touch()  # Should be ignored

        parser = SeratoParser(music_paths=[tmp_path])
        files = parser.get_all_music_files()

        assert len(files) == 3
        assert all(f.suffix in SUPPORTED_EXTENSIONS for f in files)

    def test_get_all_music_files_recursive(self, tmp_path):
        """Test scanning nested directories."""
        # Create nested structure
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        (tmp_path / "track1.mp3").touch()
        (subdir / "track2.mp3").touch()

        parser = SeratoParser(music_paths=[tmp_path])
        files = parser.get_all_music_files()

        assert len(files) == 2

    def test_ignores_serato_folder(self, tmp_path):
        """Test that _Serato_ folder contents are ignored."""
        serato_dir = tmp_path / "_Serato_"
        serato_dir.mkdir()

        (tmp_path / "track.mp3").touch()
        (serato_dir / "internal.mp3").touch()  # Should be ignored

        parser = SeratoParser(music_paths=[tmp_path])
        files = parser.get_all_music_files()

        assert len(files) == 1
        assert files[0].name == "track.mp3"

    def test_is_serato_installed_false(self, tmp_path):
        """Test Serato detection when not installed."""
        parser = SeratoParser(serato_path=tmp_path / "_Serato_")
        assert parser.is_serato_installed() is False

    def test_is_serato_installed_true(self, tmp_path):
        """Test Serato detection when installed."""
        serato_path = tmp_path / "_Serato_"
        serato_path.mkdir()

        parser = SeratoParser(serato_path=serato_path)
        assert parser.is_serato_installed() is True

    def test_get_crates_empty(self, tmp_path):
        """Test getting crates from empty Serato folder."""
        serato_path = tmp_path / "_Serato_"
        serato_path.mkdir()

        parser = SeratoParser(serato_path=serato_path)
        crates = parser.get_crates()

        assert crates == []

    def test_get_crates_no_subcrates_folder(self, tmp_path):
        """Test getting crates when Subcrates folder doesn't exist."""
        parser = SeratoParser(serato_path=tmp_path / "_Serato_")
        crates = parser.get_crates()

        assert crates == []

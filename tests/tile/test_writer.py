"""Tests for dynmap_recorder.synchronizers.tile.writer."""

import pytest
from pathlib import Path
from dynmap_recorder.synchronizers.tile.writer import TileWriter
from dynmap_recorder.synchronizers.tile.exceptions import TileWriteError


SAMPLE_BYTES = b"\x89PNG" + b"\x00" * 64


class TestWrite:
    def test_creates_file(self, tmp_path):
        dest = tmp_path / "a" / "b" / "tile.png"
        writer = TileWriter()
        writer.write(dest, SAMPLE_BYTES)
        assert dest.exists()
        assert dest.read_bytes() == SAMPLE_BYTES

    def test_creates_parent_dirs(self, tmp_path):
        dest = tmp_path / "deep" / "nested" / "path" / "tile.png"
        assert not dest.parent.exists()
        writer = TileWriter()
        writer.write(dest, SAMPLE_BYTES)
        assert dest.parent.is_dir()

    def test_overwrite_existing(self, tmp_path):
        """Writing to the same path twice should overwrite cleanly."""
        dest = tmp_path / "tile.png"
        writer = TileWriter()
        writer.write(dest, b"first content")
        writer.write(dest, b"second content")
        assert dest.read_bytes() == b"second content"

    def test_raises_tile_write_error_on_invalid_path(self):
        """Passing a path that can't be created should raise TileWriteError."""
        # Use a path whose parent is an existing *file*, not a directory
        import tempfile, os
        with tempfile.NamedTemporaryFile(delete=False) as f:
            file_as_dir = Path(f.name) / "child.png"
        try:
            writer = TileWriter()
            with pytest.raises(TileWriteError):
                writer.write(file_as_dir, SAMPLE_BYTES)
        finally:
            os.unlink(f.name)

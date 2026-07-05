"""Tile writer utility.

Provides the :class:`TileWriter` class to save raw bytes to a filesystem path.
"""

from __future__ import annotations

from pathlib import Path

from .exceptions import TileWriteError


class TileWriter:
    """Writer component for saving tile images to the filesystem."""

    def write(self, path: Path, data: bytes) -> None:
        """Write *data* to *path*, creating all parent directories as needed.

        Parameters
        ----------
        path:
            Destination file path (absolute).
        data:
            Raw bytes to write (PNG content).

        Raises
        ------
        TileWriteError
            If any filesystem operation fails.
        """
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        except OSError as exc:
            raise TileWriteError(f"Failed to write tile to {path}: {exc}") from exc

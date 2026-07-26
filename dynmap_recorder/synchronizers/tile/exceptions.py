"""Tile-synchronizer exception hierarchy.

All exceptions inherit from :class:`TileError` so callers can catch at any
level of granularity they need.
"""


class TileError(Exception):
    """Base class for all tile-synchronizer errors."""


class TileDownloadError(TileError):
    """Raised when an HTTP request fails, times out, or returns a non-2xx status."""

    def __init__(self, message: str, *, status: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class TileHashError(TileError):
    """Raised when hash computation fails (e.g. unsupported algorithm or corrupt data)."""


class TileWriteError(TileError):
    """Raised when writing a tile PNG to the filesystem fails."""


class TileDatabaseError(TileError):
    """Raised for SQLite-related errors (schema, query, or connection failures)."""


__all__ = [
    "TileError",
    "TileDownloadError",
    "TileHashError",
    "TileWriteError",
    "TileDatabaseError",
]

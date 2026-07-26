"""Tile synchronizer package.

Public API for the tile sub-package. Import everything you need from here.
"""

from .database import TileDatabase
from .downloader import DownloadResult, TileDownloader
from .exceptions import (
    TileDatabaseError,
    TileDownloadError,
    TileError,
    TileHashError,
    TileWriteError,
)
from .factory import create_default_synchronizer
from .hasher import TileHasher
from .models import HashAlgorithm, MapInfo, TileID, TileState, VisibleTile
from .path_resolver import TilePathResolver
from .scanner import VisibleTileScanner
from .settings import TileSynchronizerSettings
from .synchronizer import TileSynchronizer
from .metrics import TickMetrics
from .writer import TileWriter

__all__ = [
    # Models
    "TileID",
    "MapInfo",
    "HashAlgorithm",
    "TileState",
    "VisibleTile",
    # Configuration & Settings
    "TileSynchronizerSettings",
    # Factory
    "create_default_synchronizer",
    # Components
    "TileDownloader",
    "DownloadResult",
    "TileHasher",
    "TilePathResolver",
    "TileDatabase",
    "TileWriter",
    "VisibleTileScanner",
    # Orchestration
    "TileSynchronizer",
    "TickMetrics",
    # Exceptions
    "TileError",
    "TileDownloadError",
    "TileHashError",
    "TileWriteError",
    "TileDatabaseError",
]

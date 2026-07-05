"""Tile synchronizer models.

Consolidated data structures for the tile synchronizer.
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

# ----------------------------------------------------------------------
# Tile identifier – only positional information (map specific)
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class TileID:
    """Immutable identifier for a tile within a specific map.

    Attributes
    ----------
    map_id: int
        Identifier of the map (as defined in ``MapInfo``).
    zoom: int
        Zoom level.
    x: int
        X coordinate at the given zoom.
    y: int
        Y coordinate at the given zoom.
    """

    map_id: int
    zoom: int
    x: int
    y: int

# ----------------------------------------------------------------------
# Map configuration – holds all information required to build tile URLs
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class MapInfo:
    """Configuration for a Dynmap map.

    The fields are chosen to be sufficient for URL generation and future
    extensions (e.g., world metadata, tileset names, base URL, etc.).
    """

    id: int                 # internal map identifier
    world_name: str         # human readable world name
    world_id: int           # numeric world ID used by Dynmap
    map_name: str           # name of the map (e.g., "flat")
    prefix: str             # URL prefix for tiles (e.g., "flat")
    tileset: str            # tileset name (e.g., "flat", "cave")
    image_format: str       # e.g. "png"
    base_url: str           # base URL of the Dynmap server (no trailing slash)
    tile_size: int          # pixel size of a tile (128, 256, ...)
    max_zoom: int           # maximum zoom level supported

# ----------------------------------------------------------------------
# Supported hash algorithms – keep as Enum for extensibility
# ----------------------------------------------------------------------
class HashAlgorithm(Enum):
    """Supported hash algorithms for tile content."""

    BLAKE3 = "blake3"
    SHA256 = "sha256"

# ----------------------------------------------------------------------
# Persistent tile state – represents a row stored in the SQLite DB
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class TileState:
    """Model representing a tile row in the SQLite database.

    Attributes
    ----------
    tile: TileID
        The positional identifier.
    hash: Optional[bytes]
        Stored hash (``None`` for a brand‑new tile).
    path: Optional[Path]
        Local file system path where the PNG is stored (if any).
    downloaded_at: Optional[int]
        Epoch milliseconds of the last successful download.
    last_checked: Optional[int]
        Epoch milliseconds when the tile was last examined for changes.
    etag: Optional[str]
        HTTP ETag header, useful for conditional GETs.
    size: Optional[int]
        Size of the stored PNG in bytes.
    """

    tile: TileID
    hash: Optional[bytes]
    path: Optional[Path]
    downloaded_at: Optional[int]
    last_checked: Optional[int]
    etag: Optional[str] = None
    size: Optional[int] = None

# ----------------------------------------------------------------------
# VisibleTile – result of the scanner, carries priority information
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class VisibleTile:
    """Tile visible to a player, together with map context and priority.

    ``priority`` can be used by the synchronizer to order downloads (e.g.,
    distance from the player).  Lower numbers mean higher priority.
    """

    tile_id: TileID
    map_info: MapInfo
    priority: int = 0

__all__ = [
    "TileID",
    "MapInfo",
    "HashAlgorithm",
    "TileState",
    "VisibleTile",
]

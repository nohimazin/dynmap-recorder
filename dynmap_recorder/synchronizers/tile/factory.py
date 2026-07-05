"""Factory functions for instantiating the tile synchronizer with default dependencies.
"""

from __future__ import annotations

from .database import TileDatabase
from .downloader import TileDownloader
from .hasher import TileHasher
from .path_resolver import TilePathResolver
from .scanner import VisibleTileScanner
from .settings import TileSynchronizerSettings
from .synchronizer import TileSynchronizer
from .writer import TileWriter


def create_default_synchronizer(settings: TileSynchronizerSettings) -> TileSynchronizer:
    """Create a fully-wired :class:`TileSynchronizer` using default components.

    Parameters
    ----------
    settings:
        Configuration settings containing output root, database path, etc.
    """
    db = TileDatabase(settings.database_path)
    scanner = VisibleTileScanner()
    downloader = TileDownloader(timeout=settings.timeout)
    hasher = TileHasher(algorithm=settings.hash_algorithm)
    resolver = TilePathResolver(settings.output_root)
    writer = TileWriter()

    return TileSynchronizer(
        db=db,
        scanner=scanner,
        downloader=downloader,
        hasher=hasher,
        resolver=resolver,
        writer=writer,
    )

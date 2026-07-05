"""Tile synchroniser – pipeline coordinator.

This module coordinates the tile-update pipeline:
Scanner → URLBuilder → Downloader → Hasher → Database → PathResolver → Writer
"""

from __future__ import annotations

import logging
from pathlib import Path

from dynmap_recorder.context import TickContext

from .database import TileDatabase
from .downloader import DownloadResult, TileDownloader
from .exceptions import TileError
from .hasher import TileHasher
from .models import TileState, VisibleTile
from .path_resolver import TilePathResolver
from .scanner import VisibleTileScanner
from .writer import TileWriter

_log = logging.getLogger(__name__)


class TileSynchronizer:
    """Pipeline coordinator for tile synchronisation.

    Shares the same ``on_tick(ctx)`` interface as the recorder classes.
    Uses Dependency Injection (DI) to access all collaborator components.
    """

    def __init__(
        self,
        *,
        db: TileDatabase,
        scanner: VisibleTileScanner,
        downloader: TileDownloader,
        hasher: TileHasher,
        resolver: TilePathResolver,
        writer: TileWriter,
    ) -> None:
        """Initialize the synchronizer with required components."""
        self.db = db
        self.scanner = scanner
        self.downloader = downloader
        self.hasher = hasher
        self.resolver = resolver
        self.writer = writer

    # ------------------------------------------------------------------
    # Public interface – mirrors Recorder.on_tick(ctx)
    # ------------------------------------------------------------------

    def on_tick(self, ctx: TickContext) -> None:
        """Run the tile-synchronisation pipeline for a single poll tick.

        Parameters
        ----------
        ctx:
            The :class:`~dynmap_recorder.context.TickContext` for the current
            poll. ``ctx.timestamp`` is used as the authoritative timestamp.
        """
        visible_tiles = self.scanner.scan(ctx)

        for vt in visible_tiles:
            try:
                self._process_tile(vt, ctx)
            except TileError as exc:
                _log.error("Tile %s failed: %s", vt.tile_id, exc)
            except Exception as exc:  # noqa: BLE001
                _log.exception("Unexpected error for tile %s: %s", vt.tile_id, exc)

    # ------------------------------------------------------------------
    # Internal pipeline helper chain
    # ------------------------------------------------------------------

    def _process_tile(self, vt: VisibleTile, ctx: TickContext) -> None:
        """Process a single visible tile."""
        result = self._download(vt)
        new_hash = self.hasher.hash(result.data)
        old_state = self.db.load(vt.tile_id)

        if self._should_update(old_state, new_hash):
            path = self.resolver.resolve(vt.tile_id, vt.map_info)
            self._write_tile(path, result.data)
            new_state = self._build_state(vt, new_hash, path, result, ctx.timestamp)
            self._save_state(new_state)
            _log.debug("Updated tile %s (%d bytes)", vt.tile_id, len(result.data))
        else:
            self.db.touch(vt.tile_id, ctx.timestamp)
            _log.debug("Tile %s unchanged; touched last_checked", vt.tile_id)

    def _download(self, vt: VisibleTile) -> DownloadResult:
        """Download the tile using the downloader."""
        return self.downloader.download(vt.tile_id, vt.map_info)

    def _should_update(self, old_state: TileState | None, new_hash: bytes) -> bool:
        """Return True if the tile state should be updated based on hash differences."""
        return old_state is None or old_state.hash != new_hash

    def _write_tile(self, path: Path, data: bytes) -> None:
        """Write the tile bytes to the filesystem."""
        self.writer.write(path, data)

    def _build_state(
        self,
        vt: VisibleTile,
        new_hash: bytes,
        path: Path,
        result: DownloadResult,
        timestamp: int,
    ) -> TileState:
        """Build the new TileState object."""
        size = result.content_length or len(result.data)
        return TileState(
            tile=vt.tile_id,
            hash=new_hash,
            path=path,
            downloaded_at=timestamp,
            last_checked=timestamp,
            etag=result.etag,
            size=size,
        )

    def _save_state(self, state: TileState) -> None:
        """Save the tile state in the database."""
        self.db.save(state)

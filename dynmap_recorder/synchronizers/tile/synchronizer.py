"""Tile synchroniser – pipeline coordinator.

This module coordinates the tile-update pipeline:
Scanner → URLBuilder → Downloader → Hasher → Database → PathResolver → Writer
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List

from dynmap_recorder.context import TickContext

from .database import TileDatabase
from .downloader import DownloadResult, TileDownloader
from .exceptions import TileError
from .hasher import TileHasher
from .models import TileProcessResult, TileState, VisibleTile
from .path_resolver import TilePathResolver
from .scanner import VisibleTileScanner
from .writer import TileWriter

_log = logging.getLogger(__name__)


class TileSynchronizer:
    """Pipeline coordinator for tile synchronisation.

    Shares the same ``on_tick(ctx)`` interface as the recorder classes.
    Uses Dependency Injection (DI) to access all collaborator components.

    Worker threads handle HTTP download, hashing, and file writing.
    DB writes (``save`` / ``touch``) are aggregated on the calling thread
    inside a single ``db.transaction()`` to avoid SQLite concurrency issues.
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
        max_workers: Optional[int] = 4,
    ) -> None:
        """Initialize the synchronizer with required components.

        Parameters
        ----------
        max_workers:
            Number of threads in the ``ThreadPoolExecutor`` used to process
            tiles in parallel.  I/O‑bound work (HTTP, disk) benefits from
            values between 4 and 16; defaults to ``4``.
        """
        self.db = db
        self.scanner = scanner
        self.downloader = downloader
        self.hasher = hasher
        self.resolver = resolver
        self.writer = writer
        self.max_workers = max_workers

    # ------------------------------------------------------------------
    # Public interface – mirrors Recorder.on_tick(ctx)
    # ------------------------------------------------------------------

    def on_tick(self, ctx: TickContext) -> None:
        """Run the tile-synchronisation pipeline for a single poll tick.

        Tiles are processed in parallel (HTTP + hash + write) by a
        ``ThreadPoolExecutor``.  Once all workers complete, DB writes are
        applied atomically in a single ``transaction()`` on the calling thread.

        Parameters
        ----------
        ctx:
            The :class:`~dynmap_recorder.context.TickContext` for the current
            poll. ``ctx.timestamp`` is used as the authoritative timestamp.
        """
        visible_tiles = self.scanner.scan(ctx)
        if not visible_tiles:
            return

        old_states = {
            vt.tile_id: self.db.load(vt.tile_id)
            for vt in visible_tiles
        }

        # ---- parallel download / hash / write ----------------------------
        results: List[TileProcessResult] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._process_tile, vt, ctx, old_states.get(vt.tile_id), False): vt
                for vt in visible_tiles
            }
            for future in as_completed(futures):
                vt = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:  # noqa: BLE001
                    _log.exception("Unexpected error for tile %s: %s", vt.tile_id, exc)
                    results.append(
                        TileProcessResult(
                            tile_id=vt.tile_id,
                            checked_at=ctx.timestamp,
                            error=exc,
                        )
                    )

        # ---- aggregate DB writes in a single transaction -----------------
        with self.db.transaction():
            for result in results:
                if result.failed:
                    continue
                if result.state is not None:
                    self.db.save(result.state)
                elif result.touch_only:
                    self.db.touch(result.tile_id, result.checked_at)

    # ------------------------------------------------------------------
    # Internal pipeline helper chain
    # ------------------------------------------------------------------

    def _process_tile(
        self,
        vt: VisibleTile,
        ctx: TickContext,
        old_state: TileState | None = None,
        load_old_state: bool = True,
    ) -> TileProcessResult:
        """Process a single visible tile and return the outcome.

        **No DB writes are performed here.** The caller is responsible for
        collecting results and committing them via ``db.transaction()``.

        Returns
        -------
        TileProcessResult
            Summary of what happened: state to save, touch_only flag, error.
        """
        try:
            if load_old_state and old_state is None:
                old_state = self.db.load(vt.tile_id)
            result = self._download(vt, old_state)

            if result.status == 304:
                _log.debug("Tile %s unchanged (HTTP 304); will touch last_checked", vt.tile_id)
                return TileProcessResult(
                    tile_id=vt.tile_id,
                    touch_only=True,
                    checked_at=ctx.timestamp,
                    attempts=result.attempts,
                )

            new_hash = self.hasher.hash(result.data)

            if self._should_update(old_state, result, new_hash):
                path = self.resolver.resolve(vt.tile_id, vt.map_info)
                self._write_tile(path, result.data)
                new_state = self._build_state(vt, new_hash, path, result, ctx.timestamp)
                _log.debug("Updated tile %s (%d bytes)", vt.tile_id, len(result.data))
                return TileProcessResult(
                    tile_id=vt.tile_id,
                    state=new_state,
                    updated=True,
                    checked_at=ctx.timestamp,
                    attempts=result.attempts,
                )
            else:
                _log.debug("Tile %s unchanged (hash match); will touch last_checked", vt.tile_id)
                return TileProcessResult(
                    tile_id=vt.tile_id,
                    touch_only=True,
                    checked_at=ctx.timestamp,
                    attempts=result.attempts,
                )

        except TileError as exc:
            _log.error("Tile %s failed: %s", vt.tile_id, exc)
            return TileProcessResult(
                tile_id=vt.tile_id,
                checked_at=ctx.timestamp,
                error=exc,
            )

    def _download(self, vt: VisibleTile, old_state: TileState | None = None) -> DownloadResult:
        """Download the tile using the downloader, passing conditional headers if old_state exists."""
        etag = old_state.etag if old_state else None
        last_modified = old_state.last_modified if old_state else None
        return self.downloader.download(
            vt.tile_id,
            vt.map_info,
            etag=etag,
            last_modified=last_modified,
        )

    def _should_update(self, old_state: TileState | None, result: DownloadResult, new_hash: bytes) -> bool:
        """Return True if the tile state should be updated based on status and hash differences."""
        if result.status == 304:
            return False
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
            last_modified=result.last_modified,
        )

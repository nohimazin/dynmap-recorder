"""Tile synchroniser – pipeline coordinator.

This module coordinates the tile-update pipeline:
Scanner → URLBuilder → Downloader → Hasher → Database → PathResolver → Writer
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dynmap_recorder.context import TickContext

from .database import TileDatabase
from .downloader import DownloadResult, TileDownloader
from .exceptions import TileError
from .hasher import TileHasher
from .metrics import MetricsAggregator, TickMetrics, TileMetrics
from .models import TileID, TileProcessResult, TileState, VisibleTile
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
            tiles in parallel. I/O‑bound work (HTTP, disk) benefits from
            values between 4 and 16; defaults to ``4``.
        """
        self.db = db
        self.scanner = scanner
        self.downloader = downloader
        self.hasher = hasher
        self.resolver = resolver
        self.writer = writer
        self.max_workers = max_workers
        self._retry_tiles: List[VisibleTile] = []
        self._retry_attempts: Dict[TileID, int] = {}
        self._max_retry_attempts = 3
        self._max_retry_queue_size = 1000

    def on_start(self, config: dict, resolved_args: object, metadata_manager: object) -> None:
        """Keep the recorder lifecycle compatible with ``DynmapPoller``."""

    def on_stop(self) -> None:
        """Close the SQLite connection when the poller shuts down."""
        self.db.close()

    # ------------------------------------------------------------------
    # Public interface – mirrors Recorder.on_tick(ctx)
    # ------------------------------------------------------------------

    def on_tick(self, ctx: TickContext) -> TickMetrics:
        """Run the tile-synchronisation pipeline for a single poll tick.

        Tiles are processed in parallel (HTTP + hash + write) by a
        ``ThreadPoolExecutor``. Once all workers complete, DB writes are
        applied atomically in a single ``transaction()`` on the calling thread.

        Parameters
        ----------
        ctx:
            The :class:`~dynmap_recorder.context.TickContext` for the current
            poll. ``ctx.timestamp`` is used as the authoritative timestamp.
        """
        tick_start = time.perf_counter()
        visible_tiles = self.scanner.scan(ctx)
        retry_tiles = self._drain_retry_queue()
        tiles_to_process = self._merge_tiles(retry_tiles, visible_tiles)
        tiles_by_id = {vt.tile_id: vt for vt in tiles_to_process}

        aggregator = MetricsAggregator()

        if not tiles_to_process:
            metrics = aggregator.summary(
                scanned_tiles=len(visible_tiles),
                retry_tiles=len(retry_tiles),
                elapsed_ms=(time.perf_counter() - tick_start) * 1000.0,
            )
            _log.info(MetricsAggregator.format_log(metrics))
            return metrics

        old_states = {
            vt.tile_id: self.db.load(vt.tile_id)
            for vt in tiles_to_process
        }

        # ---- parallel download / hash / write ----------------------------
        results: List[TileProcessResult] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._process_tile, vt, ctx, old_states.get(vt.tile_id), False): vt
                for vt in tiles_to_process
            }
            for future in as_completed(futures):
                vt = futures[future]
                try:
                    p_res, m_res = future.result()
                    results.append(p_res)
                    aggregator.record(m_res)
                except Exception as exc:  # noqa: BLE001
                    _log.exception("Unexpected error for tile %s: %s", vt.tile_id, exc)
                    results.append(
                        TileProcessResult(
                            tile_id=vt.tile_id,
                            checked_at=ctx.timestamp,
                            error=exc,
                        )
                    )
                    aggregator.record(
                        TileMetrics(
                            tile_id=vt.tile_id,
                            failed=True,
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

        # ---- update retry queue -----------------------------------------
        retried, dropped = self._update_retry_queue(results, tiles_by_id)

        # ---- finalize metrics & logging ---------------------------------
        elapsed_ms = (time.perf_counter() - tick_start) * 1000.0
        metrics = aggregator.summary(
            scanned_tiles=len(visible_tiles),
            retry_tiles=len(retry_tiles),
            retried=retried,
            dropped=dropped,
            elapsed_ms=elapsed_ms,
        )
        _log.info(MetricsAggregator.format_log(metrics))
        return metrics

    # ------------------------------------------------------------------
    # Retry queue management
    # ------------------------------------------------------------------

    def _drain_retry_queue(self) -> List[VisibleTile]:
        """Return all queued retry tiles and clear the queue for this tick."""
        tiles = self._retry_tiles
        self._retry_tiles = []
        return tiles

    def _merge_tiles(
        self,
        retry_tiles: List[VisibleTile],
        visible_tiles: List[VisibleTile],
    ) -> List[VisibleTile]:
        """Combine retry and freshly scanned tiles while preserving retry priority."""
        merged: List[VisibleTile] = []
        seen: set[TileID] = set()
        for tile in retry_tiles + visible_tiles:
            if tile.tile_id in seen:
                continue
            seen.add(tile.tile_id)
            merged.append(tile)
        return merged

    def _update_retry_queue(
        self,
        results: List[TileProcessResult],
        tiles_by_id: Dict[TileID, VisibleTile],
    ) -> Tuple[int, int]:
        """Move failed tiles back into the retry queue for the next tick."""
        retried = 0
        dropped = 0
        for result in results:
            if result.failed:
                tile = tiles_by_id.get(result.tile_id)
                if tile is not None and self._should_retry(result.error):
                    if self._queue_retry(tile):
                        retried += 1
                    else:
                        dropped += 1
            else:
                self._retry_attempts.pop(result.tile_id, None)
        return retried, dropped

    def _should_retry(self, error: Exception | None) -> bool:
        """Return True when a tile failure should be retried on a later tick."""
        if not isinstance(error, TileError):
            return False
        return bool(getattr(error, "retryable", False))

    def _queue_retry(self, tile: VisibleTile) -> bool:
        """Queue a failed tile unless it has exceeded the retry limit."""
        attempts = self._retry_attempts.get(tile.tile_id, 0) + 1
        if attempts >= self._max_retry_attempts:
            _log.warning("Skipping tile %s after %d failed tick attempts", tile.tile_id, attempts)
            self._retry_attempts.pop(tile.tile_id, None)
            return False

        if len(self._retry_tiles) >= self._max_retry_queue_size:
            _log.warning("Dropping retry tile %s because the retry queue is full", tile.tile_id)
            self._retry_attempts.pop(tile.tile_id, None)
            return False

        self._retry_attempts[tile.tile_id] = attempts
        self._retry_tiles.append(tile)
        return True

    # ------------------------------------------------------------------
    # Internal pipeline helper chain
    # ------------------------------------------------------------------

    def _process_tile(
        self,
        vt: VisibleTile,
        ctx: TickContext,
        old_state: TileState | None = None,
        load_old_state: bool = True,
    ) -> Tuple[TileProcessResult, TileMetrics]:
        """Process a single visible tile and return the outcome and metrics.

        **No DB writes are performed here.** The caller is responsible for
        collecting results and committing them via ``db.transaction()``.

        Returns
        -------
        Tuple[TileProcessResult, TileMetrics]
            Summary of what happened for DB update and detailed metrics.
        """
        start_time = time.perf_counter()
        try:
            if load_old_state and old_state is None:
                old_state = self.db.load(vt.tile_id)
            result = self._download(vt, old_state)
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0

            if result.status == 304:
                _log.debug("Tile %s unchanged (HTTP 304); will touch last_checked", vt.tile_id)
                p_res = TileProcessResult(
                    tile_id=vt.tile_id,
                    touch_only=True,
                    downloaded=False,
                    checked_at=ctx.timestamp,
                )
                m_res = TileMetrics(
                    tile_id=vt.tile_id,
                    elapsed_ms=elapsed_ms,
                    retries=result.retry_count,
                    bytes_downloaded=0,
                    downloaded=False,
                    updated=False,
                    not_modified=True,
                    unchanged=False,
                    failed=False,
                )
                return p_res, m_res

            new_hash = self.hasher.hash(result.data)
            bytes_len = len(result.data)

            if self._should_update(old_state, result, new_hash):
                path = self.resolver.resolve(vt.tile_id, vt.map_info)
                self._write_tile(path, result.data)
                new_state = self._build_state(vt, new_hash, path, result, ctx.timestamp)
                _log.debug("Updated tile %s (%d bytes)", vt.tile_id, bytes_len)
                p_res = TileProcessResult(
                    tile_id=vt.tile_id,
                    state=new_state,
                    updated=True,
                    downloaded=True,
                    checked_at=ctx.timestamp,
                )
                m_res = TileMetrics(
                    tile_id=vt.tile_id,
                    elapsed_ms=elapsed_ms,
                    retries=result.retry_count,
                    bytes_downloaded=bytes_len,
                    downloaded=True,
                    updated=True,
                    not_modified=False,
                    unchanged=False,
                    failed=False,
                )
                return p_res, m_res
            else:
                _log.debug("Tile %s unchanged (hash match); will touch last_checked", vt.tile_id)
                p_res = TileProcessResult(
                    tile_id=vt.tile_id,
                    touch_only=True,
                    downloaded=True,
                    checked_at=ctx.timestamp,
                )
                m_res = TileMetrics(
                    tile_id=vt.tile_id,
                    elapsed_ms=elapsed_ms,
                    retries=result.retry_count,
                    bytes_downloaded=bytes_len,
                    downloaded=True,
                    updated=False,
                    not_modified=False,
                    unchanged=True,
                    failed=False,
                )
                return p_res, m_res

        except TileError as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            _log.error("Tile %s failed: %s", vt.tile_id, exc)
            p_res = TileProcessResult(
                tile_id=vt.tile_id,
                checked_at=ctx.timestamp,
                error=exc,
            )
            m_res = TileMetrics(
                tile_id=vt.tile_id,
                elapsed_ms=elapsed_ms,
                retries=0,
                bytes_downloaded=0,
                downloaded=False,
                updated=False,
                not_modified=False,
                unchanged=False,
                failed=True,
            )
            return p_res, m_res

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

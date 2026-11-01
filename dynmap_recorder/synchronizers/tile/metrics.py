"""Metrics collection and summary utilities for tile synchronisation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Sequence

from .models import TileID, TileProcessResult

_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TileMetrics:
    """Detailed operational metrics for processing a single tile.

    Attributes
    ----------
    tile_id:
        Identifier of the processed tile.
    elapsed_ms:
        Duration of the tile processing in milliseconds.
    retries:
        Number of HTTP retries performed by the downloader.
    bytes_downloaded:
        Number of bytes transferred (0 if HTTP 304 or failed before receiving).
    downloaded:
        True if an HTTP 200 response with tile data was received.
    updated:
        True if the tile was new or changed and saved to disk.
    not_modified:
        True if the server returned HTTP 304 Not Modified.
    unchanged:
        True if the server returned HTTP 200 but the hash matched existing state.
    failed:
        True if processing failed with an exception.
    """

    tile_id: TileID
    elapsed_ms: float = 0.0
    retries: int = 0
    bytes_downloaded: int = 0
    downloaded: bool = False
    updated: bool = False
    not_modified: bool = False
    unchanged: bool = False
    failed: bool = False


@dataclass(slots=True)
class TickMetrics:
    """Operational metrics returned for one tile-synchronisation tick."""

    scanned_tiles: int = 0
    retry_tiles: int = 0
    downloaded: int = 0
    updated: int = 0
    touched: int = 0
    failed: int = 0
    retried: int = 0
    dropped: int = 0
    elapsed_ms: float = 0.0
    bytes_downloaded: int = 0
    http_retries: int = 0
    not_modified: int = 0
    unchanged: int = 0

    @classmethod
    def from_results(
        cls,
        *,
        scanned_tiles: int,
        retry_tiles: int,
        results: Sequence[TileProcessResult],
        retried: int,
        dropped: int,
        elapsed_ms: float,
    ) -> "TickMetrics":
        """Compatibility helper to compute metrics directly from process results."""
        return cls(
            scanned_tiles=scanned_tiles,
            retry_tiles=retry_tiles,
            downloaded=sum(1 for result in results if result.downloaded or result.updated),
            updated=sum(1 for result in results if result.updated),
            touched=sum(1 for result in results if result.touch_only),
            failed=sum(1 for result in results if result.failed),
            retried=retried,
            dropped=dropped,
            elapsed_ms=elapsed_ms,
        )


class MetricsAggregator:
    """Thread-safe collector used on the main thread to aggregate tile metrics."""

    def __init__(self) -> None:
        self._tile_metrics: List[TileMetrics] = []

    def record(self, metrics: TileMetrics) -> None:
        """Record a single TileMetrics instance."""
        self._tile_metrics.append(metrics)

    def summary(
        self,
        *,
        scanned_tiles: int = 0,
        retry_tiles: int = 0,
        retried: int = 0,
        dropped: int = 0,
        elapsed_ms: float = 0.0,
    ) -> TickMetrics:
        """Summarize all recorded tile metrics into a TickMetrics instance."""
        downloaded = sum(1 for m in self._tile_metrics if m.downloaded)
        updated = sum(1 for m in self._tile_metrics if m.updated)
        touched = sum(1 for m in self._tile_metrics if m.not_modified or m.unchanged)
        failed = sum(1 for m in self._tile_metrics if m.failed)
        not_modified = sum(1 for m in self._tile_metrics if m.not_modified)
        unchanged = sum(1 for m in self._tile_metrics if m.unchanged)
        bytes_downloaded = sum(m.bytes_downloaded for m in self._tile_metrics)
        http_retries = sum(m.retries for m in self._tile_metrics)

        return TickMetrics(
            scanned_tiles=scanned_tiles,
            retry_tiles=retry_tiles,
            downloaded=downloaded,
            updated=updated,
            touched=touched,
            failed=failed,
            retried=retried,
            dropped=dropped,
            elapsed_ms=elapsed_ms,
            bytes_downloaded=bytes_downloaded,
            http_retries=http_retries,
            not_modified=not_modified,
            unchanged=unchanged,
        )

    def reset(self) -> None:
        """Clear recorded tile metrics."""
        self._tile_metrics.clear()

    @staticmethod
    def format_log(metrics: TickMetrics, tick_number: int | None = None) -> str:
        """Format the tick metrics for logging."""
        tick_label = f"Tick #{tick_number}" if tick_number is not None else "Tick"
        elapsed_sec = metrics.elapsed_ms / 1000.0 if metrics.elapsed_ms > 0 else 0.0
        total_tiles = metrics.scanned_tiles + metrics.retry_tiles
        throughput = (total_tiles / elapsed_sec) if elapsed_sec > 0 else 0.0

        b = metrics.bytes_downloaded
        if b >= 1024 * 1024:
            b_str = f"{b / (1024 * 1024):.1f} MB"
        elif b >= 1024:
            b_str = f"{b / 1024:.1f} KB"
        else:
            b_str = f"{b} B"

        lines = [
            f"Tile Synchronizer — {tick_label}",
            f"Updated: {metrics.updated} | HTTP 304: {metrics.not_modified} | Unchanged (200): {metrics.unchanged} | Failed: {metrics.failed}",
            "------------------------------------------------------------",
            f"Scanned: {metrics.scanned_tiles} | Downloaded: {metrics.downloaded} | Bytes: {b_str}",
            f"HTTP retries: {metrics.http_retries} | Queue retries: {metrics.retry_tiles} | Queued: {metrics.retried} | Dropped: {metrics.dropped}",
            f"Processing time: {elapsed_sec:.2f} sec | Throughput: {throughput:.1f} tiles/sec",
        ]
        return "\n".join(lines)


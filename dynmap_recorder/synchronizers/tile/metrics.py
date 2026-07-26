"""Metrics collection and summary utilities for tile synchronisation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Sequence

from .models import TileID, TileProcessResult

_log = logging.getLogger(__name__)


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
        return cls(
            scanned_tiles=scanned_tiles,
            retry_tiles=retry_tiles,
            downloaded=sum(1 for result in results if result.downloaded),
            updated=sum(1 for result in results if result.updated),
            touched=sum(1 for result in results if result.touch_only),
            failed=sum(1 for result in results if result.failed),
            retried=retried,
            dropped=dropped,
            elapsed_ms=elapsed_ms,
        )


@dataclass(frozen=True)
class TileMetrics:
    """Metrics for processing a single tile during a tick.

    Attributes
    ----------
    tile_id:
        Identifier of the processed tile.
    retries:
        Number of retry attempts required (attempts - 1).
    updated:
        True if the tile content was downloaded and saved.
    touch_only:
        True if the tile content was unchanged.
    failed:
        True if an error occurred during tile processing.
    """

    tile_id: TileID
    retries: int = 0
    updated: bool = False
    touch_only: bool = False
    failed: bool = False

    @classmethod
    def from_result(cls, res: TileProcessResult) -> TileMetrics:
        """Construct a :class:`TileMetrics` from a :class:`TileProcessResult`."""
        retries = max(0, res.attempts - 1)
        return cls(
            tile_id=res.tile_id,
            retries=retries,
            updated=res.updated,
            touch_only=res.touch_only,
            failed=res.failed,
        )


@dataclass(frozen=True)
class TickMetricsSummary:
    """Aggregated summary of all tiles processed during a single poll tick.

    Attributes
    ----------
    total_scanned:
        Total number of visible tiles scanned in this tick.
    updated:
        Number of tiles newly saved or updated on disk.
    touched:
        Number of tiles examined but found unchanged (304 or hash match).
    failed:
        Number of tiles that failed due to errors.
    total_retries:
        Total retry attempts performed across all tiles.
    elapsed_sec:
        Total duration of the tick poll in seconds.
    throughput:
        Processing rate in tiles per second.
    """

    total_scanned: int
    updated: int
    touched: int
    failed: int
    total_retries: int
    elapsed_sec: float
    throughput: float


class MetricsCollector:
    """Collector for accumulating per-tile metrics and computing summary statistics."""

    def __init__(self) -> None:
        self._tile_metrics: List[TileMetrics] = []

    def add_result(self, res: TileProcessResult) -> None:
        """Convert a process result to tile metrics and record it."""
        self._tile_metrics.append(TileMetrics.from_result(res))

    def add_results(self, results: Sequence[TileProcessResult]) -> None:
        """Record multiple process results."""
        for res in results:
            self.add_result(res)

    def summarize(self, elapsed_sec: float) -> TickMetricsSummary:
        """Compute aggregated summary metrics for the accumulated tiles.

        Parameters
        ----------
        elapsed_sec:
            Duration of the poll tick in seconds.
        """
        total = len(self._tile_metrics)
        updated = sum(1 for m in self._tile_metrics if m.updated)
        touched = sum(1 for m in self._tile_metrics if m.touch_only)
        failed = sum(1 for m in self._tile_metrics if m.failed)
        retries = sum(m.retries for m in self._tile_metrics)
        throughput = (total / elapsed_sec) if elapsed_sec > 0 else 0.0

        return TickMetricsSummary(
            total_scanned=total,
            updated=updated,
            touched=touched,
            failed=failed,
            total_retries=retries,
            elapsed_sec=elapsed_sec,
            throughput=throughput,
        )

    def log_summary(self, summary: TickMetricsSummary) -> None:
        """Log the summary in a readable format."""
        _log.info(
            "Tile poll tick completed in %.2fs (%.1f tiles/s) | "
            "total: %d, updated: %d, touched: %d, failed: %d, retries: %d",
            summary.elapsed_sec,
            summary.throughput,
            summary.total_scanned,
            summary.updated,
            summary.touched,
            summary.failed,
            summary.total_retries,
        )

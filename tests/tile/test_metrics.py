from dynmap_recorder.synchronizers.tile.metrics import MetricsAggregator, TickMetrics, TileMetrics
from dynmap_recorder.context import TickContext
from dynmap_recorder.synchronizers.tile.database import TileDatabase
from dynmap_recorder.synchronizers.tile.downloader import DownloadResult
from dynmap_recorder.synchronizers.tile.hasher import TileHasher
from dynmap_recorder.synchronizers.tile.models import MapInfo, TileID, TileProcessResult, VisibleTile, HashAlgorithm
from dynmap_recorder.synchronizers.tile.path_resolver import TilePathResolver
from dynmap_recorder.synchronizers.tile.synchronizer import TileSynchronizer
from dynmap_recorder.synchronizers.tile.writer import TileWriter
from unittest.mock import MagicMock


def test_tick_metrics_counts_results():
    results = [
        TileProcessResult(tile_id=TileID(1, 0, 0, 0), updated=True, downloaded=True),
        TileProcessResult(tile_id=TileID(1, 0, 1, 0), touch_only=True, downloaded=False),
        TileProcessResult(tile_id=TileID(1, 0, 2, 0), error=RuntimeError("failed")),
    ]

    metrics = TickMetrics.from_results(
        scanned_tiles=3,
        retry_tiles=1,
        results=results,
        retried=1,
        dropped=1,
        elapsed_ms=12.5,
    )

    assert metrics.scanned_tiles == 3
    assert metrics.retry_tiles == 1
    assert metrics.downloaded == 1
    assert metrics.updated == 1
    assert metrics.touched == 1
    assert metrics.failed == 1
    assert metrics.retried == 1
    assert metrics.dropped == 1
    assert metrics.elapsed_ms == 12.5


def test_retry_queue_has_bounded_size():
    synchronizer = TileSynchronizer(
        db=MagicMock(),
        scanner=MagicMock(),
        downloader=MagicMock(),
        hasher=MagicMock(),
        resolver=MagicMock(),
        writer=MagicMock(),
    )
    synchronizer._max_retry_queue_size = 1

    first = MagicMock()
    first.tile_id = TileID(1, 0, 0, 0)
    second = MagicMock()
    second.tile_id = TileID(1, 0, 1, 0)

    assert synchronizer._queue_retry(first) is True
    assert synchronizer._queue_retry(second) is False
    assert len(synchronizer._retry_tiles) == 1


def test_sync_pipeline_writes_tile_and_persists_state(tmp_path):
    tile_id = TileID(1, 0, 0, 0)
    map_info = MapInfo(
        id=1,
        world_name="world",
        world_id=0,
        map_name="flat",
        prefix="flat",
        tileset="flat",
        image_format="png",
        base_url="http://example.test",
        tile_size=128,
        max_zoom=0,
    )
    visible_tile = VisibleTile(tile_id=tile_id, map_info=map_info)
    db = TileDatabase(tmp_path / "tiles.db")
    scanner = MagicMock()
    scanner.scan.return_value = [visible_tile]
    downloader = MagicMock()
    downloader.download.return_value = DownloadResult(status=200, data=b"tile-bytes", etag='"v1"')
    synchronizer = TileSynchronizer(
        db=db,
        scanner=scanner,
        downloader=downloader,
        hasher=TileHasher(HashAlgorithm.SHA256),
        resolver=TilePathResolver(tmp_path / "tiles"),
        writer=TileWriter(),
        max_workers=1,
    )
    ctx = MagicMock(spec=TickContext)
    ctx.timestamp = 1234

    metrics = synchronizer.on_tick(ctx)

    state = db.load(tile_id)
    assert metrics.updated == 1
    assert metrics.downloaded == 1
    assert state is not None
    tile_path = (tmp_path / "tiles" / "world" / "flat" / "flat" / "z0" / "0" / "0.png").resolve()
    assert tile_path.read_bytes() == b"tile-bytes"
    assert state.etag == '"v1"'
    synchronizer.on_stop()


def test_metrics_aggregator_records_and_summarizes():
    aggregator = MetricsAggregator()
    aggregator.record(TileMetrics(
        tile_id=TileID(1, 0, 0, 0),
        elapsed_ms=10.0,
        retries=2,
        bytes_downloaded=1024,
        downloaded=True,
        updated=True,
    ))
    aggregator.record(TileMetrics(
        tile_id=TileID(1, 0, 1, 0),
        elapsed_ms=5.0,
        retries=0,
        bytes_downloaded=0,
        not_modified=True,
    ))
    aggregator.record(TileMetrics(
        tile_id=TileID(1, 0, 2, 0),
        elapsed_ms=8.0,
        retries=1,
        bytes_downloaded=2048,
        downloaded=True,
        unchanged=True,
    ))
    aggregator.record(TileMetrics(
        tile_id=TileID(1, 0, 3, 0),
        elapsed_ms=15.0,
        retries=0,
        bytes_downloaded=0,
        failed=True,
    ))

    summary = aggregator.summary(
        scanned_tiles=4,
        retry_tiles=1,
        retried=1,
        dropped=0,
        elapsed_ms=100.0,
    )

    assert summary.scanned_tiles == 4
    assert summary.retry_tiles == 1
    assert summary.downloaded == 2
    assert summary.updated == 1
    assert summary.not_modified == 1
    assert summary.unchanged == 1
    assert summary.touched == 2  # not_modified + unchanged
    assert summary.failed == 1
    assert summary.http_retries == 3
    assert summary.bytes_downloaded == 3072
    assert summary.retried == 1
    assert summary.dropped == 0
    assert summary.elapsed_ms == 100.0


def test_metrics_aggregator_reset():
    aggregator = MetricsAggregator()
    aggregator.record(TileMetrics(tile_id=TileID(1, 0, 0, 0), updated=True))
    assert len(aggregator._tile_metrics) == 1
    aggregator.reset()
    assert len(aggregator._tile_metrics) == 0


def test_metrics_aggregator_format_log():
    metrics = TickMetrics(
        scanned_tiles=128,
        retry_tiles=3,
        downloaded=54,
        updated=43,
        not_modified=72,
        unchanged=11,
        touched=83,
        failed=2,
        retried=2,
        dropped=0,
        elapsed_ms=1320.0,
        bytes_downloaded=1258291,  # ~1.2 MB
        http_retries=5,
    )
    log_text = MetricsAggregator.format_log(metrics, tick_number=42)

    assert "Tick #42" in log_text
    assert "Updated: 43" in log_text
    assert "HTTP 304: 72" in log_text
    assert "Unchanged (200): 11" in log_text
    assert "Failed: 2" in log_text
    assert "Scanned: 128" in log_text
    assert "Downloaded: 54" in log_text
    assert "1.2 MB" in log_text
    assert "HTTP retries: 5" in log_text
    assert "Queue retries: 3" in log_text
    assert "Queued: 2" in log_text
    assert "Dropped: 0" in log_text
    assert "1.32 sec" in log_text


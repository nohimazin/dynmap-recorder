from dynmap_recorder.synchronizers.tile.metrics import TickMetrics
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

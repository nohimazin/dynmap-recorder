"""Tests for the TileSynchronizer coordinator and its DI/factory flow."""

from pathlib import Path
from unittest.mock import MagicMock, call, patch
import threading

import pytest

from dynmap_recorder.context import TickContext
from dynmap_recorder.synchronizers.tile.database import TileDatabase
from dynmap_recorder.synchronizers.tile.downloader import DownloadResult, TileDownloader
from dynmap_recorder.synchronizers.tile.exceptions import TileDownloadError, TileError
from dynmap_recorder.synchronizers.tile.factory import create_default_synchronizer
from dynmap_recorder.synchronizers.tile.hasher import TileHasher
from dynmap_recorder.synchronizers.tile.models import HashAlgorithm, MapInfo, TileID, TileProcessResult, TileState, VisibleTile
from dynmap_recorder.synchronizers.tile.path_resolver import TilePathResolver
from dynmap_recorder.synchronizers.tile.scanner import VisibleTileScanner
from dynmap_recorder.synchronizers.tile.settings import TileSynchronizerSettings
from dynmap_recorder.synchronizers.tile.synchronizer import TileSynchronizer
from dynmap_recorder.synchronizers.tile.writer import TileWriter


@pytest.fixture
def map_info():
    return MapInfo(
        id=1,
        world_name="world",
        world_id=0,
        map_name="surface",
        prefix="tiles",
        tileset="flat",
        image_format="png",
        base_url="http://example.com",
        tile_size=128,
        max_zoom=3,
    )


@pytest.fixture
def tile_id():
    return TileID(map_id=1, zoom=2, x=10, y=20)


@pytest.fixture
def dummy_ctx():
    ctx = MagicMock(spec=TickContext)
    ctx.timestamp = 123456789
    return ctx


def test_should_update():
    synchronizer = TileSynchronizer(
        db=MagicMock(),
        scanner=MagicMock(),
        downloader=MagicMock(),
        hasher=MagicMock(),
        resolver=MagicMock(),
        writer=MagicMock(),
    )
    result_200 = DownloadResult(status=200, data=b"data")
    result_304 = DownloadResult(status=304, data=b"")

    # If no old state, should update
    assert synchronizer._should_update(None, result_200, b"new") is True

    # If status is 304, should not update
    assert synchronizer._should_update(None, result_304, b"new") is False

    # If hash differs, should update
    old_state = TileState(tile=TileID(1, 2, 3, 4), hash=b"old", path=None, downloaded_at=0, last_checked=0)
    assert synchronizer._should_update(old_state, result_200, b"new") is True

    # If hash is same, should not update
    assert synchronizer._should_update(old_state, result_200, b"old") is False


def test_process_tile_new_or_changed(dummy_ctx, tile_id, map_info):
    """_process_tile() for a new/changed tile should return a result with state set (no DB write)."""
    db = MagicMock(spec=TileDatabase)
    db.load.return_value = None  # simulating new tile

    scanner = MagicMock(spec=VisibleTileScanner)
    downloader = MagicMock(spec=TileDownloader)
    result = DownloadResult(status=200, data=b"png_data", etag='"etag_123"', last_modified="Mon, 01 Jan 2026 00:00:00 GMT", content_length=8)
    downloader.download.return_value = result

    hasher = MagicMock(spec=TileHasher)
    hasher.hash.return_value = b"new_hash_val"

    resolver = MagicMock(spec=TilePathResolver)
    resolved_path = Path("/mock/outputs/tiles/world/surface/flat/z2/10/20.png")
    resolver.resolve.return_value = resolved_path

    writer = MagicMock(spec=TileWriter)

    synchronizer = TileSynchronizer(
        db=db,
        scanner=scanner,
        downloader=downloader,
        hasher=hasher,
        resolver=resolver,
        writer=writer,
    )

    vt = VisibleTile(tile_id=tile_id, map_info=map_info, priority=1.0)
    process_result = synchronizer._process_tile(vt, dummy_ctx)

    # HTTP, hasher, writer all called
    downloader.download.assert_called_once_with(tile_id, map_info, etag=None, last_modified=None)
    hasher.hash.assert_called_once_with(b"png_data")
    db.load.assert_called_once_with(tile_id)
    resolver.resolve.assert_called_once_with(tile_id, map_info)
    writer.write.assert_called_once_with(resolved_path, b"png_data")

    # _process_tile must NOT touch the DB directly
    db.save.assert_not_called()
    db.touch.assert_not_called()

    # Result fields
    assert isinstance(process_result, TileProcessResult)
    assert process_result.failed is False
    assert process_result.updated is True
    assert process_result.touch_only is False
    assert process_result.state is not None
    assert process_result.state.tile == tile_id
    assert process_result.state.hash == b"new_hash_val"
    assert process_result.state.path == resolved_path
    assert process_result.state.downloaded_at == dummy_ctx.timestamp
    assert process_result.state.last_checked == dummy_ctx.timestamp
    assert process_result.state.etag == '"etag_123"'
    assert process_result.state.size == 8
    assert process_result.state.last_modified == "Mon, 01 Jan 2026 00:00:00 GMT"


def test_process_tile_unchanged(dummy_ctx, tile_id, map_info):
    """_process_tile() for an unchanged tile (hash match) returns touch_only=True, no DB write."""
    db = MagicMock(spec=TileDatabase)
    old_state = TileState(
        tile=tile_id,
        hash=b"same_hash_val",
        path=Path("some/path"),
        downloaded_at=1000,
        last_checked=1000,
        etag='"etag_123"',
        last_modified="Mon, 01 Jan 2026 00:00:00 GMT",
    )
    db.load.return_value = old_state

    scanner = MagicMock(spec=VisibleTileScanner)
    downloader = MagicMock(spec=TileDownloader)
    result = DownloadResult(status=200, data=b"png_data", etag='"etag_123"', last_modified="Mon, 01 Jan 2026 00:00:00 GMT")
    downloader.download.return_value = result

    hasher = MagicMock(spec=TileHasher)
    hasher.hash.return_value = b"same_hash_val"

    resolver = MagicMock(spec=TilePathResolver)
    writer = MagicMock(spec=TileWriter)

    synchronizer = TileSynchronizer(
        db=db,
        scanner=scanner,
        downloader=downloader,
        hasher=hasher,
        resolver=resolver,
        writer=writer,
    )

    vt = VisibleTile(tile_id=tile_id, map_info=map_info, priority=1.0)
    process_result = synchronizer._process_tile(vt, dummy_ctx)

    downloader.download.assert_called_once_with(tile_id, map_info, etag='"etag_123"', last_modified="Mon, 01 Jan 2026 00:00:00 GMT")
    hasher.hash.assert_called_once_with(b"png_data")
    db.load.assert_called_once_with(tile_id)

    # Unchanged tile: no file writes, no DB writes from _process_tile
    resolver.resolve.assert_not_called()
    writer.write.assert_not_called()
    db.save.assert_not_called()
    db.touch.assert_not_called()

    # Result indicates touch is needed
    assert isinstance(process_result, TileProcessResult)
    assert process_result.failed is False
    assert process_result.updated is False
    assert process_result.touch_only is True
    assert process_result.state is None
    assert process_result.tile_id == tile_id
    assert process_result.checked_at == dummy_ctx.timestamp


def test_process_tile_304_not_modified(dummy_ctx, tile_id, map_info):
    """_process_tile() for a 304 response returns touch_only=True, no DB write."""
    db = MagicMock(spec=TileDatabase)
    old_state = TileState(
        tile=tile_id,
        hash=b"same_hash_val",
        path=Path("some/path"),
        downloaded_at=1000,
        last_checked=1000,
        etag='"etag_123"',
        last_modified="Mon, 01 Jan 2026 00:00:00 GMT",
    )
    db.load.return_value = old_state

    scanner = MagicMock(spec=VisibleTileScanner)
    downloader = MagicMock(spec=TileDownloader)
    result = DownloadResult(status=304, data=b"")  # HTTP 304 Not Modified response
    downloader.download.return_value = result

    hasher = MagicMock(spec=TileHasher)
    resolver = MagicMock(spec=TilePathResolver)
    writer = MagicMock(spec=TileWriter)

    synchronizer = TileSynchronizer(
        db=db,
        scanner=scanner,
        downloader=downloader,
        hasher=hasher,
        resolver=resolver,
        writer=writer,
    )

    vt = VisibleTile(tile_id=tile_id, map_info=map_info, priority=1.0)
    process_result = synchronizer._process_tile(vt, dummy_ctx)

    downloader.download.assert_called_once_with(tile_id, map_info, etag='"etag_123"', last_modified="Mon, 01 Jan 2026 00:00:00 GMT")
    # Hasher, writer, and DB must not be called from _process_tile
    hasher.hash.assert_not_called()
    resolver.resolve.assert_not_called()
    writer.write.assert_not_called()
    db.save.assert_not_called()
    db.touch.assert_not_called()

    # Result indicates touch is needed
    assert isinstance(process_result, TileProcessResult)
    assert process_result.failed is False
    assert process_result.updated is False
    assert process_result.touch_only is True
    assert process_result.state is None
    assert process_result.tile_id == tile_id
    assert process_result.checked_at == dummy_ctx.timestamp


def test_on_tick_with_multiple_tiles_and_error_handling(dummy_ctx, tile_id, map_info):
    """on_tick() runs tiles in parallel; failed tile is skipped in DB aggregation."""
    db = MagicMock(spec=TileDatabase)
    # transaction() context manager must be a real contextmanager for this test
    from contextlib import contextmanager
    @contextmanager
    def fake_transaction():
        yield db
    db.transaction = fake_transaction
    db.load.return_value = None

    scanner = MagicMock(spec=VisibleTileScanner)
    vt1 = VisibleTile(tile_id=tile_id, map_info=map_info, priority=1.0)
    # create second tile
    tile_id2 = TileID(map_id=1, zoom=2, x=11, y=20)
    vt2 = VisibleTile(tile_id=tile_id2, map_info=map_info, priority=2.0)
    scanner.scan.return_value = [vt1, vt2]

    downloader = MagicMock(spec=TileDownloader)
    # tile 1 fails, tile 2 succeeds – side_effect is per-call regardless of thread order
    def download_side_effect(tile_id_arg, map_info_arg, **kwargs):
        if tile_id_arg == tile_id:
            raise TileDownloadError("Failed to fetch")
        return DownloadResult(status=200, data=b"png_data_2")
    downloader.download.side_effect = download_side_effect

    hasher = MagicMock(spec=TileHasher)
    hasher.hash.return_value = b"hash2"

    resolver = MagicMock(spec=TilePathResolver)
    resolver.resolve.return_value = Path("path2")

    writer = MagicMock(spec=TileWriter)

    synchronizer = TileSynchronizer(
        db=db,
        scanner=scanner,
        downloader=downloader,
        hasher=hasher,
        resolver=resolver,
        writer=writer,
        max_workers=2,
    )

    synchronizer.on_tick(dummy_ctx)

    # Both downloads were attempted
    assert downloader.download.call_count == 2

    # Successful tile (tile2): hasher, writer, and db.save called
    hasher.hash.assert_called_once_with(b"png_data_2")
    writer.write.assert_called_once_with(Path("path2"), b"png_data_2")
    db.save.assert_called_once()
    assert db.save.call_args[0][0].tile == tile_id2
    # Failed tile (tile1): no touch or save
    db.touch.assert_not_called()


def test_on_tick_partial_failures_in_parallel_batch(dummy_ctx, map_info):
    """When processing 20 tiles in parallel, exceptions on specific tiles do not prevent others from saving."""
    db = MagicMock(spec=TileDatabase)
    from contextlib import contextmanager
    @contextmanager
    def fake_transaction():
        yield db
    db.transaction = fake_transaction
    db.load.return_value = None

    scanner = MagicMock(spec=VisibleTileScanner)
    # Generate 20 tiles
    visible_tiles = [
        VisibleTile(tile_id=TileID(map_id=1, zoom=0, x=i, y=0), map_info=map_info, priority=i)
        for i in range(20)
    ]
    scanner.scan.return_value = visible_tiles

    downloader = MagicMock(spec=TileDownloader)
    # Tiles where x % 5 == 0 fail with TileDownloadError
    def download_side_effect(tile_id_arg, map_info_arg, **kwargs):
        if tile_id_arg.x % 5 == 0:
            raise TileDownloadError(f"Simulated network error for tile x={tile_id_arg.x}")
        return DownloadResult(status=200, data=f"data_{tile_id_arg.x}".encode())

    downloader.download.side_effect = download_side_effect

    hasher = MagicMock(spec=TileHasher)
    hasher.hash.side_effect = lambda data: b"hash_" + data

    resolver = MagicMock(spec=TilePathResolver)
    resolver.resolve.side_effect = lambda tid, minfo: Path(f"/tiles/{tid.x}.png")

    writer = MagicMock(spec=TileWriter)

    synchronizer = TileSynchronizer(
        db=db,
        scanner=scanner,
        downloader=downloader,
        hasher=hasher,
        resolver=resolver,
        writer=writer,
        max_workers=4,
    )

    synchronizer.on_tick(dummy_ctx)

    # Total downloads attempted: 20
    assert downloader.download.call_count == 20

    # 4 tiles failed (0, 5, 10, 15), 16 succeeded
    assert db.save.call_count == 16
    saved_tile_xs = {call_args[0][0].tile.x for call_args in db.save.call_args_list}
    expected_xs = {i for i in range(20) if i % 5 != 0}
    assert saved_tile_xs == expected_xs


def test_on_tick_loads_db_states_on_main_thread(dummy_ctx, tile_id, map_info):
    db = MagicMock(spec=TileDatabase)
    load_threads: list[str] = []

    def load_side_effect(tile_id_arg):
        load_threads.append(threading.current_thread().name)
        return None

    db.load.side_effect = load_side_effect

    from contextlib import contextmanager

    @contextmanager
    def fake_transaction():
        yield db

    db.transaction = fake_transaction

    scanner = MagicMock(spec=VisibleTileScanner)
    scanner.scan.return_value = [
        VisibleTile(tile_id=tile_id, map_info=map_info, priority=1.0),
        VisibleTile(tile_id=TileID(map_id=1, zoom=2, x=11, y=20), map_info=map_info, priority=2.0),
    ]

    downloader = MagicMock(spec=TileDownloader)
    downloader.download.return_value = DownloadResult(status=200, data=b"data")

    hasher = MagicMock(spec=TileHasher)
    hasher.hash.return_value = b"hash"

    resolver = MagicMock(spec=TilePathResolver)
    resolver.resolve.return_value = Path("path")

    writer = MagicMock(spec=TileWriter)

    synchronizer = TileSynchronizer(
        db=db,
        scanner=scanner,
        downloader=downloader,
        hasher=hasher,
        resolver=resolver,
        writer=writer,
        max_workers=2,
    )

    synchronizer.on_tick(dummy_ctx)

    assert load_threads
    assert set(load_threads) == {"MainThread"}


def test_factory_creates_correct_instances(tmp_path):
    settings = TileSynchronizerSettings(
        output_root=tmp_path / "tiles",
        database_path=tmp_path / "tile.db",
        timeout=15,
        hash_algorithm=HashAlgorithm.SHA256,
    )

    synchronizer = create_default_synchronizer(settings)

    assert isinstance(synchronizer, TileSynchronizer)
    assert isinstance(synchronizer.db, TileDatabase)
    assert synchronizer.db.db_path == settings.database_path
    assert isinstance(synchronizer.scanner, VisibleTileScanner)
    assert isinstance(synchronizer.downloader, TileDownloader)
    assert synchronizer.downloader.timeout == 15
    assert isinstance(synchronizer.hasher, TileHasher)
    assert synchronizer.hasher.algorithm == HashAlgorithm.SHA256
    assert isinstance(synchronizer.resolver, TilePathResolver)
    assert synchronizer.resolver.root == settings.output_root
    assert isinstance(synchronizer.writer, TileWriter)

    # Clean up DB connection
    synchronizer.db.close()

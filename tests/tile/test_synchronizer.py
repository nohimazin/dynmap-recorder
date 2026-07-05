"""Tests for the TileSynchronizer coordinator and its DI/factory flow."""

from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

from dynmap_recorder.context import TickContext
from dynmap_recorder.synchronizers.tile.database import TileDatabase
from dynmap_recorder.synchronizers.tile.downloader import DownloadResult, TileDownloader
from dynmap_recorder.synchronizers.tile.exceptions import TileDownloadError, TileError
from dynmap_recorder.synchronizers.tile.factory import create_default_synchronizer
from dynmap_recorder.synchronizers.tile.hasher import TileHasher
from dynmap_recorder.synchronizers.tile.models import HashAlgorithm, MapInfo, TileID, TileState, VisibleTile
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

    # If no old state, should update
    assert synchronizer._should_update(None, b"new") is True

    # If hash differs, should update
    old_state = TileState(tile=TileID(1, 2, 3, 4), hash=b"old", path=None, downloaded_at=0, last_checked=0)
    assert synchronizer._should_update(old_state, b"new") is True

    # If hash is same, should not update
    assert synchronizer._should_update(old_state, b"old") is False


def test_process_tile_new_or_changed(dummy_ctx, tile_id, map_info):
    db = MagicMock(spec=TileDatabase)
    db.load.return_value = None  # simulating new tile

    scanner = MagicMock(spec=VisibleTileScanner)
    downloader = MagicMock(spec=TileDownloader)
    result = DownloadResult(status=200, data=b"png_data", etag='"etag_123"', content_length=8)
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
    synchronizer._process_tile(vt, dummy_ctx)

    downloader.download.assert_called_once_with(tile_id, map_info)
    hasher.hash.assert_called_once_with(b"png_data")
    db.load.assert_called_once_with(tile_id)
    resolver.resolve.assert_called_once_with(tile_id, map_info)
    writer.write.assert_called_once_with(resolved_path, b"png_data")

    # State built with correct parameters
    db.save.assert_called_once()
    saved_state = db.save.call_args[0][0]
    assert saved_state.tile == tile_id
    assert saved_state.hash == b"new_hash_val"
    assert saved_state.path == resolved_path
    assert saved_state.downloaded_at == dummy_ctx.timestamp
    assert saved_state.last_checked == dummy_ctx.timestamp
    assert saved_state.etag == '"etag_123"'
    assert saved_state.size == 8


def test_process_tile_unchanged(dummy_ctx, tile_id, map_info):
    db = MagicMock(spec=TileDatabase)
    old_state = TileState(
        tile=tile_id,
        hash=b"same_hash_val",
        path=Path("some/path"),
        downloaded_at=1000,
        last_checked=1000,
    )
    db.load.return_value = old_state

    scanner = MagicMock(spec=VisibleTileScanner)
    downloader = MagicMock(spec=TileDownloader)
    result = DownloadResult(status=200, data=b"png_data")
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
    synchronizer._process_tile(vt, dummy_ctx)

    downloader.download.assert_called_once_with(tile_id, map_info)
    hasher.hash.assert_called_once_with(b"png_data")
    db.load.assert_called_once_with(tile_id)

    # Unchanged tile should NOT write files or save state, only touch last_checked
    resolver.resolve.assert_not_called()
    writer.write.assert_not_called()
    db.save.assert_not_called()
    db.touch.assert_called_once_with(tile_id, dummy_ctx.timestamp)


def test_on_tick_with_multiple_tiles_and_error_handling(dummy_ctx, tile_id, map_info):
    db = MagicMock(spec=TileDatabase)
    db.load.return_value = None

    scanner = MagicMock(spec=VisibleTileScanner)
    vt1 = VisibleTile(tile_id=tile_id, map_info=map_info, priority=1.0)
    # create second tile
    tile_id2 = TileID(map_id=1, zoom=2, x=11, y=20)
    vt2 = VisibleTile(tile_id=tile_id2, map_info=map_info, priority=2.0)
    scanner.scan.return_value = [vt1, vt2]

    downloader = MagicMock(spec=TileDownloader)
    # tile 1 fails, tile 2 succeeds
    downloader.download.side_effect = [
        TileDownloadError("Failed to fetch"),
        DownloadResult(status=200, data=b"png_data_2"),
    ]

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
    )

    synchronizer.on_tick(dummy_ctx)

    # Both downloads attempted
    assert downloader.download.call_count == 2
    downloader.download.assert_has_calls([
        call(tile_id, map_info),
        call(tile_id2, map_info),
    ])

    # Second tile proceeds, first one fails but doesn't halt the tick
    hasher.hash.assert_called_once_with(b"png_data_2")
    writer.write.assert_called_once_with(Path("path2"), b"png_data_2")
    db.save.assert_called_once()
    assert db.save.call_args[0][0].tile == tile_id2


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

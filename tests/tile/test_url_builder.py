"""Tests for dynmap_recorder.synchronizers.tile.url_builder."""

import pytest
from dynmap_recorder.synchronizers.tile.models import MapInfo, TileID
from dynmap_recorder.synchronizers.tile.url_builder import build_url


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
        base_url="http://example.com/dynmap",
        tile_size=128,
        max_zoom=3,
    )


@pytest.fixture
def tile_id():
    return TileID(map_id=1, zoom=2, x=10, y=20)


def test_url_basic_format(map_info, tile_id):
    url = build_url(tile_id, map_info)
    assert url == "http://example.com/dynmap/tiles/flat/2/10_20.png"


def test_url_trailing_slash_stripped():
    mi = MapInfo(
        id=1,
        world_name="world",
        world_id=0,
        map_name="surface",
        prefix="tiles",
        tileset="flat",
        image_format="png",
        base_url="http://example.com/dynmap/",  # trailing slash
        tile_size=128,
        max_zoom=3,
    )
    tile = TileID(map_id=1, zoom=0, x=0, y=0)
    url = build_url(tile, mi)
    assert not url.startswith("http://example.com/dynmap//")
    assert url.startswith("http://example.com/dynmap/")


def test_url_different_zoom_xy(map_info):
    tile = TileID(map_id=1, zoom=3, x=-1, y=5)
    url = build_url(tile, map_info)
    assert "/3/" in url
    assert "-1_5.png" in url

"""Tests for dynmap_recorder.synchronizers.tile.path_resolver."""

from pathlib import Path
import pytest
from dynmap_recorder.synchronizers.tile.models import MapInfo, TileID
from dynmap_recorder.synchronizers.tile.path_resolver import TilePathResolver


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


def test_path_ends_with_png(map_info, tile_id, tmp_path):
    resolver = TilePathResolver(tmp_path)
    p = resolver.resolve(tile_id, map_info)
    assert p.suffix == ".png"


def test_path_directory_structure(map_info, tile_id, tmp_path):
    resolver = TilePathResolver(tmp_path)
    p = resolver.resolve(tile_id, map_info)
    parts = p.parts
    # Should contain world_name, map_name, tileset, zoom dir, x dir, y.png
    assert "world" in parts
    assert "surface" in parts
    assert "flat" in parts
    assert "z2" in parts
    assert "10" in parts
    assert p.name == "20.png"


def test_path_is_absolute(map_info, tile_id, tmp_path):
    resolver = TilePathResolver(tmp_path)
    p = resolver.resolve(tile_id, map_info)
    assert p.is_absolute()


def test_path_uses_map_image_format(map_info, tile_id, tmp_path):
    map_info = MapInfo(**{**map_info.__dict__, "image_format": "jpg"})
    resolver = TilePathResolver(tmp_path)
    assert resolver.resolve(tile_id, map_info).name == "20.jpg"

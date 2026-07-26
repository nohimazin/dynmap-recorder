"""Tests for the VisibleTileScanner coordinate conversion and priority grid scanning."""

import pytest
from unittest.mock import MagicMock

from dynmap_recorder.context import TickContext
from dynmap_recorder.player_state import PlayerState
from dynmap_recorder.metadata import MetadataManager
from dynmap_recorder.synchronizers.tile.models import TileID, VisibleTile
from dynmap_recorder.synchronizers.tile.scanner import VisibleTileScanner, better_round


def test_better_round():
    # Formula: int(base * ceil(num / tile_size))
    # tile_size=128 (default): num is scaled into tile-units before rounding.

    # --- tile_size=128 (default) ---
    # 0 / 128 = 0.0 → ceil = 0 → 1*0 = 0
    assert better_round(0.0, 1) == 0
    # 128 / 128 = 1.0 → ceil = 1 → 1*1 = 1
    assert better_round(128.0, 1) == 1
    # 12.8 / 128 = 0.1 → ceil = 1 → 1*1 = 1
    assert better_round(12.8, 1) == 1
    # 256 / 128 = 2.0 → ceil = 2 → 2*2 = 4  (base=2)
    assert better_round(256.0, 2) == 4
    # 512 / 128 = 4.0 → ceil = 4 → 2*4 = 8
    assert better_round(512.0, 2) == 8

    # --- tile_size=1 (unit tile size, equivalent to old raw formula) ---
    # With tile_size=1: scaled = num, formula = int(base * ceil(num))
    assert better_round(0.0, 1, tile_size=1) == 0
    assert better_round(0.1, 1, tile_size=1) == 1
    assert better_round(1.0, 1, tile_size=1) == 1
    assert better_round(1.1, 1, tile_size=1) == 2
    assert better_round(-0.5, 1, tile_size=1) == 0
    assert better_round(-1.0, 1, tile_size=1) == -1
    assert better_round(-1.5, 1, tile_size=1) == -1

    # With tile_size=1 and base=2: int(2 * ceil(num))
    assert better_round(0.0, 2, tile_size=1) == 0
    assert better_round(0.5, 2, tile_size=1) == 2   # ceil(0.5)=1 → 2*1=2
    assert better_round(1.0, 2, tile_size=1) == 2   # ceil(1.0)=1 → 2*1=2
    assert better_round(1.1, 2, tile_size=1) == 4   # ceil(1.1)=2 → 2*2=4
    assert better_round(-0.5, 2, tile_size=1) == 0  # ceil(-0.5)=0 → 2*0=0
    assert better_round(-1.0, 2, tile_size=1) == -2 # ceil(-1.0)=-1 → 2*-1=-2
    assert better_round(-1.5, 2, tile_size=1) == -2 # ceil(-1.5)=-1 → 2*-1=-2



@pytest.fixture
def dynmap_config():
    return {
        "worlds": [
            {
                "name": "world",
                "title": "World Name",
                "maps": [
                    {
                        "name": "flat",
                        "prefix": "flat",
                        "tileset": "flat",
                        "image_format": "png",
                        "tile_size": 128,
                        "maxzoom": 1,
                        "worldtomap": [1.0, 0.0, 0.0, 0.0, 0.0, -1.0],  # standard flat projection: xx=x, yy=-z
                    },
                    {
                        "name": "surface",
                        "prefix": "surface",
                        "tileset": "flat",
                        "image_format": "png",
                        "tile_size": 128,
                        "maxzoom": 0,
                        "worldtomap": [0.5, 0.0, -0.5, -0.25, 0.5, -0.25],  # standard isometric projection
                    }
                ]
            }
        ]
    }


@pytest.fixture
def dummy_ctx():
    metadata = MagicMock(spec=MetadataManager)
    metadata.worlds_by_id = {1: "world", 2: "nether"}

    # Mock player states
    player1 = PlayerState(
        player_id=1, world_id=1, x=150.0, y=64.0, z=-300.0,
        yaw=0.0, pitch=0.0, hp=20.0, armor=0.0, online=True
    )
    player2 = PlayerState(
        player_id=2, world_id=1, x=160.0, y=64.0, z=-300.0,
        yaw=0.0, pitch=0.0, hp=20.0, armor=0.0, online=True
    )
    player_nether = PlayerState(
        player_id=3, world_id=2, x=0.0, y=64.0, z=0.0,
        yaw=0.0, pitch=0.0, hp=20.0, armor=0.0, online=True
    )

    ctx = MagicMock(spec=TickContext)
    ctx.world_id = 1  # active world = "world"
    ctx.metadata = metadata
    ctx.player_cache = {1: player1, 2: player2, 3: player_nether}
    return ctx


def test_scanner_no_matching_world(dummy_ctx, dynmap_config):
    # Change active world to nether, which doesn't exist in dynmap_config
    dummy_ctx.world_id = 2
    scanner = VisibleTileScanner(dynmap_config=dynmap_config, scan_radius=1, base_url="http://localhost")
    tiles = scanner.scan(dummy_ctx)
    assert tiles == []


def test_scanner_flat_projection_and_radius(dummy_ctx, dynmap_config):
    # Scan radius = 1 tile around player.
    # Player 1 is at x=150, z=-300.
    # Flat map: xx = x = 150.0, yy = -z = 300.0
    # For zoom 0 (zs=1):
    # cx = better_round(150.0/128, 1) = better_round(1.17, 1) = 2
    # cy = better_round(-(128-300)/128, 1) = better_round(172/128, 1) = better_round(1.34, 1) = 2
    # Center tile = (2, 2). Grid range for dx, dy in [-1, 1] means tiles from 1 to 3 in x/y.

    scanner = VisibleTileScanner(dynmap_config=dynmap_config, scan_radius=1, base_url="http://localhost")
    tiles = scanner.scan(dummy_ctx)

    # We have flat map (maxzoom=1) and surface map (maxzoom=0).
    # Flat map has zoom 0 and zoom 1.
    # Surface map has zoom 0 only.
    # Total unique tiles should be found and sorted by distance.
    assert len(tiles) > 0

    # Let's filter to just the flat map (map_id = 0)
    flat_tiles = [vt for vt in tiles if vt.map_info.id == 0]
    zoom0_flat_tiles = [vt for vt in flat_tiles if vt.tile_id.zoom == 0]

    # Grid radius = 1 around center (2, 2)
    # tx in [1, 2, 3], ty in [1, 2, 3] -> 9 tiles total
    assert len(zoom0_flat_tiles) == 9

    # Check center tile is present and has priority = 0.0 (closest to player)
    center_vt = next(vt for vt in zoom0_flat_tiles if vt.tile_id.x == 2 and vt.tile_id.y == 2)
    assert center_vt.priority == 0.0

    # Ensure list is sorted by priority ascending
    priorities = [vt.priority for vt in tiles]
    assert priorities == sorted(priorities)


def test_scanner_de_duplication(dummy_ctx, dynmap_config):
    # Player 1 and Player 2 are close (x=150 vs x=160). Both center on (2, 2) on flat map.
    # Ensure they do not produce duplicate tiles in the output.
    scanner = VisibleTileScanner(dynmap_config=dynmap_config, scan_radius=1, base_url="http://localhost")
    tiles = scanner.scan(dummy_ctx)

    flat_tiles_z0 = [vt for vt in tiles if vt.map_info.id == 0 and vt.tile_id.zoom == 0]
    # Unique tile keys
    tile_coords = [(vt.tile_id.x, vt.tile_id.y) for vt in flat_tiles_z0]
    assert len(tile_coords) == len(set(tile_coords))  # No duplicates


def test_scanner_projection_cache_isolated_by_world():
    dynmap_config = {
        "worlds": [
            {
                "name": "world",
                "maps": [
                    {
                        "name": "map",
                        "prefix": "map",
                        "tileset": "flat",
                        "image_format": "png",
                        "tile_size": 128,
                        "maxzoom": 0,
                        "worldtomap": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
                    }
                ],
            },
            {
                "name": "nether",
                "maps": [
                    {
                        "name": "map",
                        "prefix": "map",
                        "tileset": "flat",
                        "image_format": "png",
                        "tile_size": 128,
                        "maxzoom": 0,
                        "worldtomap": [0.0, 0.0, 1.0, 0.0, 1.0, 0.0],
                    }
                ],
            },
        ]
    }

    scanner = VisibleTileScanner(dynmap_config=dynmap_config, scan_radius=1, base_url="http://localhost")

    metadata = MagicMock(spec=MetadataManager)
    metadata.worlds_by_id = {1: "world", 2: "nether"}

    ctx = MagicMock(spec=TickContext)
    ctx.metadata = metadata
    ctx.player_cache = {
        1: PlayerState(player_id=1, world_id=1, x=150.0, y=64.0, z=300.0, yaw=0.0, pitch=0.0, hp=20.0, armor=0.0, online=True),
        2: PlayerState(player_id=2, world_id=2, x=150.0, y=64.0, z=300.0, yaw=0.0, pitch=0.0, hp=20.0, armor=0.0, online=True),
    }

    ctx.world_id = 1
    world_tiles = scanner.scan(ctx)
    ctx.world_id = 2
    nether_tiles = scanner.scan(ctx)

    assert world_tiles
    assert nether_tiles
    assert world_tiles[0].tile_id != nether_tiles[0].tile_id

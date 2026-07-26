"""Visible-tile scanner.

Determines which tiles are visible based on online player locations and active map configurations.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple
from dataclasses import dataclass

from dynmap_recorder.context import TickContext
from .models import MapInfo, TileID, VisibleTile

@dataclass(frozen=True)
class ProjectionInfo:
    """Cached projection information for a map."""
    worldtomap: Tuple[float, ...]
    tile_size: int
    max_zoom: int



def better_round(num: float, base: int, tile_size: int = 128) -> int:
    """Round a number to the nearest multiple of base, scaled by tile_size.
    The original implementation always used a tile size of 128. This version makes the size configurable.
    """
    # Scale the number by tile_size before applying the base rounding.
    scaled = float(num) / tile_size
    return int(base * math.ceil(scaled))


class VisibleTileScanner:
    """Scanner to determine which tiles need to be synchronised for a tick.

    Converts Minecraft block coordinates of online players into Dynmap tile
    coordinates using matrix-based projections.
    """

    def __init__(
        self,
        dynmap_config: Dict[str, Any] | None = None,
        scan_radius: int = 2,
        base_url: str = "",
    ) -> None:
        """Initialize the scanner.

        Parameters
        ----------
        dynmap_config:
            The raw dictionary representation of the Dynmap configuration JSON.
        scan_radius:
            Radius in tiles to scan around each player.
        base_url:
            Base URL of the Dynmap server.
        """
        self.dynmap_config = dynmap_config or {}
        self.scan_radius = scan_radius
        self.base_url = base_url.rstrip("/")
        # Cache projection information for faster repeated projections
        # Mapping: map index -> ProjectionInfo
        self._projection_cache: Dict[int, ProjectionInfo] = {}
        # Pre‑populate cache with maps that already exist in the config
        for world in self.dynmap_config.get("worlds", []):
            for idx, mc in enumerate(world.get("maps", [])):
                worldtomap = mc.get("worldtomap", [1.0, 0.0, 0.0, 0.0, 1.0, 0.0])
                tile_size = mc.get("tile_size", 128)
                max_zoom = mc.get("maxzoom", 0)
                self._projection_cache[idx] = ProjectionInfo(
                    worldtomap=tuple(worldtomap),
                    tile_size=tile_size,
                    max_zoom=max_zoom,
                )

    def _project_player(self, map_info, player):
        """Project Minecraft coordinates to Dynmap plane using cached matrix."""
        wtm = self._projection_cache.get(map_info.id)
        if wtm is None:
            wtm = ProjectionInfo(
                worldtomap=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
                tile_size=128,
                max_zoom=0,
            )
            self._projection_cache[map_info.id] = wtm
        xx = wtm.worldtomap[0] * player.x + wtm.worldtomap[1] * player.y + wtm.worldtomap[2] * player.z
        yy = wtm.worldtomap[3] * player.x + wtm.worldtomap[4] * player.y + wtm.worldtomap[5] * player.z
        return xx, yy

    def _center_tile(self, xx: float, yy: float, map_info, zs: int):
        """Compute center tile coordinates for given world coordinates.

        Uses the map's tile_size (default 128) and the zoom level's scaling factor.
        """
        tile_size = map_info.tile_size
        cx = better_round(xx, zs, tile_size)
        cy = better_round(-(tile_size - yy), zs, tile_size)
        return cx, cy

    def scan(self, ctx: TickContext) -> List[VisibleTile]:
        """Return tiles that should be synchronised for this tick.

        Parameters
        ----------
        ctx:
            The :class:`~dynmap_recorder.context.TickContext` for the current poll.
        """
        # Resolve active world name
        world_name = ctx.metadata.worlds_by_id.get(ctx.world_id)
        if not world_name:
            return []

        # Find the active world's map configurations
        worlds = self.dynmap_config.get("worlds", [])
        world_config = None
        for w in worlds:
            if w.get("name") == world_name:
                world_config = w
                break

        if not world_config:
            return []

        maps_config = world_config.get("maps", [])
        if not maps_config:
            return []

        # Gather players currently in this active world
        active_players = []
        for player_state in ctx.player_cache.values():
            if player_state.world_id == ctx.world_id:
                active_players.append(player_state)

        if not active_players:
            return []

        # We will collect unique tiles and track the minimum grid distance to any player
        # Key: (map_index, zoom, tx, ty) -> (VisibleTile, min_dist)
        unique_tiles: Dict[Tuple[int, int, int, int], Tuple[VisibleTile, float]] = {}

        for map_idx, mc in enumerate(maps_config):
            # Parse map configuration
            map_name = mc.get("name", "")
            prefix = mc.get("prefix", map_name)
            tileset = mc.get("tileset", prefix)
            image_format = mc.get("image_format", "png")
            tile_size = mc.get("tile_size", 128)
            max_zoom = mc.get("maxzoom", 0)
            if max_zoom < 0:
                max_zoom = 0

            # Use cached world‑to‑map matrix if available, otherwise store it
            wtm = self._projection_cache.get(map_idx)
            if wtm is None:
                wtm = ProjectionInfo(
                    worldtomap=tuple(mc.get("worldtomap", [1.0, 0.0, 0.0, 0.0, 1.0, 0.0])),
                    tile_size=mc.get("tile_size", 128),
                    max_zoom=max_zoom,
                )
                self._projection_cache[map_idx] = wtm

            map_info = MapInfo(
                id=map_idx,
                world_name=world_name,
                world_id=ctx.world_id,
                map_name=map_name,
                prefix=prefix,
                tileset=tileset,
                image_format=image_format,
                base_url=self.base_url,
                tile_size=tile_size,
                max_zoom=max_zoom,
            )

            for player in active_players:
                # Project Minecraft coords (x, y, z) into 2D plane coordinates
                xx, yy = self._project_player(map_info, player)

                # Scan at each zoom level
                for zoom in range(max_zoom + 1):
                    zs = 2**zoom
                    r_at_zoom = max(1, self.scan_radius // zs)

                    # Compute center tile coordinates (multiples of zs)
                    cx, cy = self._center_tile(xx, yy, map_info, zs)

                    # Scan the square grid around the center
                    for dx in range(-r_at_zoom, r_at_zoom + 1):
                        for dy in range(-r_at_zoom, r_at_zoom + 1):
                            tx = cx + dx * zs
                            ty = cy + dy * zs

                            dist = math.sqrt(dx**2 + dy**2)
                            key = (map_idx, zoom, tx, ty)

                            if key in unique_tiles:
                                # Update minimum distance/priority
                                existing_tile, existing_dist = unique_tiles[key]
                                if dist < existing_dist:
                                    unique_tiles[key] = (
                                        VisibleTile(
                                            tile_id=existing_tile.tile_id,
                                            map_info=existing_tile.map_info,
                                            priority=dist,
                                        ),
                                        dist,
                                    )
                            else:
                                tile_id = TileID(map_id=map_idx, zoom=zoom, x=tx, y=ty)
                                unique_tiles[key] = (
                                    VisibleTile(
                                        tile_id=tile_id,
                                        map_info=map_info,
                                        priority=dist,
                                    ),
                                    dist,
                                )

        # Sort visible tiles by priority (distance) ascending so tiles closer to players sync first
        sorted_tiles = [vt for vt, _ in sorted(unique_tiles.values(), key=lambda item: item[1])]
        return sorted_tiles

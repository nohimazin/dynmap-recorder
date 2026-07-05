"""Utility to resolve local filesystem paths for storing tile images.
"""

from __future__ import annotations

from pathlib import Path

from .models import MapInfo, TileID


class TilePathResolver:
    """Resolver component for tile storage paths."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def resolve(self, tile: TileID, map_info: MapInfo) -> Path:
        """Return the absolute path where a tile PNG should be stored.

        Directory layout:
        <root>/<world_name>/<map_name>/<tileset>/z<zoom>/<x>/<y>.png

        Parameters
        ----------
        tile:
            Positional identifier of the tile.
        map_info:
            Configuration containing map-specific parameters.
        """
        path = (
            self.root
            / map_info.world_name
            / map_info.map_name
            / map_info.tileset
            / f"z{tile.zoom}"
            / str(tile.x)
            / f"{tile.y}.png"
        )
        return path.resolve()

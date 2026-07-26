# dynmap_recorder/synchronizers/tile/url_builder.py
"""Utility to build Dynmap tile URLs.

The function is pure and stateless, making it easy to test.
"""

from .models import TileID, MapInfo


def build_url(tile: TileID, map_info: MapInfo) -> str:
    """Construct the full URL for a tile.

    Dynmap tile URL format (example)::
        {base_url}/tiles/{world}/{prefix}/{chunk_x}_{chunk_y}/{zoom_prefix}{x}_{y}.{image_format}

    Parameters
    ----------
    tile: TileID
        Positional identifier of the tile.
    map_info: MapInfo
        Configuration containing base URL and other map‑specific parameters.
    """
    base = map_info.base_url.rstrip('/')
    chunk_x = tile.x >> 5
    chunk_y = tile.y >> 5
    zoom_prefix = "" if tile.zoom == 0 else f"{'z' * tile.zoom}_"
    return (
        f"{base}/tiles/{map_info.world_name}/{map_info.prefix}/"
        f"{chunk_x}_{chunk_y}/{zoom_prefix}{tile.x}_{tile.y}.{map_info.image_format}"
    )

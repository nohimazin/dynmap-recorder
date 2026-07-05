# dynmap_recorder/synchronizers/tile/url_builder.py
"""Utility to build Dynmap tile URLs.

The function is pure and stateless, making it easy to test.
"""

from .models import TileID, MapInfo


def build_url(tile: TileID, map_info: MapInfo) -> str:
    """Construct the full URL for a tile.

    Dynmap tile URL format (example)::
        {base_url}/{prefix}/{tileset}/{zoom}/{x}_{y}.{image_format}

    Parameters
    ----------
    tile: TileID
        Positional identifier of the tile.
    map_info: MapInfo
        Configuration containing base URL and other map‑specific parameters.
    """
    # Ensure no trailing slash on base_url
    base = map_info.base_url.rstrip('/')
    return f"{base}/{map_info.prefix}/{map_info.tileset}/{tile.zoom}/{tile.x}_{tile.y}.{map_info.image_format}"

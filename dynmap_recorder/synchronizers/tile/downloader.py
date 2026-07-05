"""Downloader utility for fetching tile PNG bytes.

The :class:`TileDownloader` component is responsible for building the URL
(using the pure ``build_url`` function) and performing the HTTP request.  It
returns a simplified :class:`DownloadResult` containing only the fields the
synchronizer needs.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional, Sequence, List, Tuple

from .exceptions import TileDownloadError
from .url_builder import build_url  # pure function


@dataclass(frozen=True)
class DownloadResult:
    """Result of a single HTTP tile download.

    Only the metadata required by the synchronizer is stored.
    """

    status: int                     # HTTP status code (e.g. 200, 304)
    data: bytes
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    content_length: Optional[int] = None


class TileDownloader:
    """Downloader component for the tile pipeline.

    The downloader knows how to build the URL for a given tile and performs the
    HTTP request.  The only configurable attribute is the request timeout.
    """

    def __init__(self, timeout: int = 10) -> None:
        self.timeout = timeout

    def download(self, tile_id, map_info) -> DownloadResult:
        """Download the tile identified by ``tile_id`` and ``map_info``.

        The URL is constructed using the pure ``build_url`` function.  The
        method returns a :class:`DownloadResult` with the response data and the
        relevant HTTP headers.
        """
        url = build_url(tile_id, map_info)
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = resp.read()
                status = resp.status
                hdr = resp.headers
                return DownloadResult(
                    status=status,
                    data=data,
                    etag=hdr.get("ETag"),
                    last_modified=hdr.get("Last-Modified"),
                    content_length=int(hdr.get("Content-Length"))
                    if hdr.get("Content-Length") is not None
                    else None,
                )
        except urllib.error.HTTPError as exc:
            raise TileDownloadError(
                f"HTTP {exc.code} {exc.reason} for {url}"
            ) from exc
        except urllib.error.URLError as exc:
            raise TileDownloadError(
                f"Network error for {url}: {exc.reason}"
            ) from exc
        except TimeoutError as exc:
            raise TileDownloadError(f"Timeout fetching {url}") from exc
        except OSError as exc:
            raise TileDownloadError(f"OS error for {url}: {exc}") from exc

    def download_many(self, items: Sequence[Tuple]) -> List[DownloadResult]:
        """Download a sequence of ``(tile_id, map_info)`` pairs sequentially.

        This helper mirrors the future‑parallel API but currently performs the
        downloads one after another.
        """
        return [self.download(tile_id, map_info) for tile_id, map_info in items]

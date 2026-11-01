"""Downloader utility for fetching tile PNG bytes.

The :class:`TileDownloader` component is responsible for building the URL
(using the pure ``build_url`` function) and performing the HTTP request.  It
returns a simplified :class:`DownloadResult` containing only the fields the
synchronizer needs.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional, Sequence, List, Tuple

from .exceptions import TileDownloadError
from .url_builder import build_url  # pure function


@dataclass(frozen=True)
class RetryPolicy:
    """Configuration policy for HTTP download retries.

    Attributes
    ----------
    retries: int
        Maximum number of retry attempts (default: 3).
    initial_delay: float
        Initial wait time in seconds before the first retry (default: 0.5).
    backoff: float
        Multiplier applied to the delay after each retry (default: 2.0).
    max_delay: float
        Maximum delay ceiling in seconds between retries (default: 10.0).
    """

    retries: int = 3
    initial_delay: float = 0.5
    backoff: float = 2.0
    max_delay: float = 10.0


def _should_retry(exc: Exception) -> bool:
    """Determine whether an exception during download is transient and retryable.

    Returns True for:
    - HTTP 500, 502, 503, 504 server errors
    - URLError (network connectivity / DNS issues)
    - TimeoutError / ConnectionResetError / OSError (socket/connection timeouts)
    """
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in (500, 502, 503, 504)
    if isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionResetError, OSError)):
        return True
    return False


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
    retry_count: int = 0


class TileDownloader:
    """Downloader component for the tile pipeline.

    The downloader knows how to build the URL for a given tile and performs the
    HTTP request with optional retries.
    """

    def __init__(
        self,
        timeout: int = 10,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self.timeout = timeout
        self.retry_policy = retry_policy

    def download(
        self,
        tile_id: TileID,
        map_info: MapInfo,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> DownloadResult:
        """Download the tile identified by ``tile_id`` and ``map_info``.

        The URL is constructed using the pure ``build_url`` function.  If a
        retry policy is specified, transient errors (e.g. 5xx, timeouts) are
        retried automatically with exponential backoff.
        """
        url = build_url(tile_id, map_info)
        max_attempts = (self.retry_policy.retries + 1) if self.retry_policy else 1
        current_delay = self.retry_policy.initial_delay if self.retry_policy else 0.0

        for attempt in range(1, max_attempts + 1):
            try:
                req = urllib.request.Request(url)
                if etag:
                    req.add_header("If-None-Match", etag)
                if last_modified:
                    req.add_header("If-Modified-Since", last_modified)
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
                        retry_count=attempt - 1,
                    )
            except urllib.error.HTTPError as exc:
                if exc.code == 304:
                    return DownloadResult(
                        status=304,
                        data=b"",
                        etag=exc.headers.get("ETag"),
                        last_modified=exc.headers.get("Last-Modified"),
                        content_length=0,
                        retry_count=attempt - 1,
                    )
                if attempt < max_attempts and _should_retry(exc):
                    time.sleep(current_delay)
                    current_delay = min(
                        current_delay * self.retry_policy.backoff,
                        self.retry_policy.max_delay,
                    )
                    continue
                raise TileDownloadError(
                    f"HTTP {exc.code} {exc.reason} for {url}"
                ) from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt < max_attempts and _should_retry(exc):
                    time.sleep(current_delay)
                    current_delay = min(
                        current_delay * self.retry_policy.backoff,
                        self.retry_policy.max_delay,
                    )
                    continue
                if isinstance(exc, urllib.error.URLError):
                    raise TileDownloadError(f"Network error for {url}: {exc.reason}") from exc
                if isinstance(exc, TimeoutError):
                    raise TileDownloadError(f"Timeout fetching {url}") from exc
                raise TileDownloadError(f"OS error for {url}: {exc}") from exc

        raise TileDownloadError(f"Failed to fetch {url} after {max_attempts} attempts")

    def download_many(self, items: Sequence[Tuple]) -> List[DownloadResult]:
        """Download a sequence of ``(tile_id, map_info)`` pairs sequentially.

        This helper mirrors the future‑parallel API but currently performs the
        downloads one after another.
        """
        return [self.download(tile_id, map_info) for tile_id, map_info in items]

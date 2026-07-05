"""Tests for dynmap_recorder.synchronizers.tile.downloader."""

import socket
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from dynmap_recorder.synchronizers.tile.downloader import DownloadResult, TileDownloader
from dynmap_recorder.synchronizers.tile.exceptions import TileDownloadError
from dynmap_recorder.synchronizers.tile.models import MapInfo, TileID


FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50


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


def _make_mock_response(
    body: bytes,
    status: int = 200,
    etag: str | None = None,
    content_length: int | None = None,
    last_modified: str | None = None,
):
    """Helper to build a mock HTTP response."""
    headers = MagicMock()
    headers.get = lambda key, default=None: {
        "ETag": etag,
        "Content-Length": str(content_length) if content_length is not None else None,
        "Last-Modified": last_modified,
    }.get(key, default)

    response = MagicMock()
    response.__enter__ = lambda s: s
    response.__exit__ = MagicMock(return_value=False)
    response.read.return_value = body
    response.status = status
    response.headers = headers
    return response


class TestDownloadResult:
    def test_is_frozen(self):
        r = DownloadResult(data=b"x", status=200)
        with pytest.raises((AttributeError, TypeError)):
            r.status = 404  # type: ignore[misc]

    def test_optional_fields_default_none(self):
        r = DownloadResult(data=b"x", status=200)
        assert r.etag is None
        assert r.content_length is None
        assert r.last_modified is None


class TestDownload:
    def test_successful_download(self, tile_id, map_info):
        mock_response = _make_mock_response(
            FAKE_PNG,
            status=200,
            etag='"abc"',
            content_length=len(FAKE_PNG),
            last_modified="Sat, 01 Jan 2000 00:00:00 GMT",
        )
        downloader = TileDownloader()
        with patch("urllib.request.urlopen", return_value=mock_response):
            result = downloader.download(tile_id, map_info)

        assert isinstance(result, DownloadResult)
        assert result.data == FAKE_PNG
        assert result.status == 200
        assert result.etag == '"abc"'
        assert result.content_length == len(FAKE_PNG)
        assert result.last_modified == "Sat, 01 Jan 2000 00:00:00 GMT"

    def test_no_optional_headers(self, tile_id, map_info):
        mock_response = _make_mock_response(FAKE_PNG, status=200)
        downloader = TileDownloader()
        with patch("urllib.request.urlopen", return_value=mock_response):
            result = downloader.download(tile_id, map_info)

        assert result.etag is None
        assert result.content_length is None
        assert result.last_modified is None

    def test_http_error_raises_tile_download_error(self, tile_id, map_info):
        downloader = TileDownloader()
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(
                url="http://x", code=404, msg="Not Found", hdrs=None, fp=None
            ),
        ):
            with pytest.raises(TileDownloadError, match="404"):
                downloader.download(tile_id, map_info)

    def test_url_error_raises_tile_download_error(self, tile_id, map_info):
        downloader = TileDownloader()
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("Name or service not known"),
        ):
            with pytest.raises(TileDownloadError):
                downloader.download(tile_id, map_info)

    def test_timeout_raises_tile_download_error(self, tile_id, map_info):
        downloader = TileDownloader(timeout=1)
        with patch(
            "urllib.request.urlopen",
            side_effect=TimeoutError("timed out"),
        ):
            with pytest.raises(TileDownloadError, match="[Tt]imeout"):
                downloader.download(tile_id, map_info)

    def test_download_many(self, tile_id, map_info):
        mock_response = _make_mock_response(FAKE_PNG, status=200)
        downloader = TileDownloader()
        with patch("urllib.request.urlopen", return_value=mock_response):
            results = downloader.download_many([(tile_id, map_info), (tile_id, map_info)])
        assert len(results) == 2
        assert all(isinstance(r, DownloadResult) for r in results)

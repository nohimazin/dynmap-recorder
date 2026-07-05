"""Tests for dynmap_recorder.synchronizers.tile.hasher."""

import pytest
from unittest.mock import patch

from dynmap_recorder.synchronizers.tile.exceptions import TileHashError
from dynmap_recorder.synchronizers.tile.hasher import TileHasher, hash_bytes
from dynmap_recorder.synchronizers.tile.models import HashAlgorithm


SAMPLE_DATA = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # fake PNG bytes


class TestSha256:
    def test_returns_bytes(self):
        hasher = TileHasher(HashAlgorithm.SHA256)
        result = hasher.hash(SAMPLE_DATA)
        assert isinstance(result, bytes)
        assert len(result) == 32  # SHA-256 produces 32 bytes

    def test_deterministic_100_times(self):
        """Same data hashed 100 times must always yield the same digest."""
        hasher = TileHasher(HashAlgorithm.SHA256)
        digests = {hasher.hash(SAMPLE_DATA) for _ in range(100)}
        assert len(digests) == 1

    def test_different_data_different_hash(self):
        hasher = TileHasher(HashAlgorithm.SHA256)
        h1 = hasher.hash(b"abc")
        h2 = hasher.hash(b"def")
        assert h1 != h2

    def test_verify_method(self):
        hasher = TileHasher(HashAlgorithm.SHA256)
        h = hasher.hash(b"abc")
        assert hasher.verify(b"abc", h) is True
        assert hasher.verify(b"def", h) is False


class TestBlake3Fallback:
    def test_falls_back_to_sha256_when_import_fails(self):
        """When blake3 is not installed, hasher should silently use SHA-256."""
        import sys

        # Force blake3 import to fail
        with patch.dict(sys.modules, {"blake3": None}):
            hasher = TileHasher(HashAlgorithm.BLAKE3)
            result = hasher.hash(SAMPLE_DATA)
        # Should still return bytes of some length (SHA-256 = 32 bytes)
        assert isinstance(result, bytes)
        assert len(result) == 32

    def test_explicit_sha256_never_calls_blake3(self):
        """Explicit SHA256 choice must not involve blake3 at all."""
        with patch("dynmap_recorder.synchronizers.tile.hasher._sha256") as mock_sha:
            mock_sha.return_value = b"\x00" * 32
            hasher = TileHasher(HashAlgorithm.SHA256)
            hasher.hash(SAMPLE_DATA)
            mock_sha.assert_called_once()


class TestBlake3Native:
    def test_blake3_if_available(self):
        """If blake3 is installed, result should be 32 bytes."""
        pytest.importorskip("blake3")
        hasher = TileHasher(HashAlgorithm.BLAKE3)
        result = hasher.hash(SAMPLE_DATA)
        assert isinstance(result, bytes)
        assert len(result) == 32

    def test_blake3_deterministic(self):
        pytest.importorskip("blake3")
        hasher = TileHasher(HashAlgorithm.BLAKE3)
        digests = {hasher.hash(SAMPLE_DATA) for _ in range(100)}
        assert len(digests) == 1

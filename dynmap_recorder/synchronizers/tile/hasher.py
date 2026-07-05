"""Tile hash computation utilities.

This module provides the :class:`TileHasher` class to compute and verify tile content hashes.
"""

from __future__ import annotations

import hashlib
import logging

from .exceptions import TileHashError
from .models import HashAlgorithm

_log = logging.getLogger(__name__)

# Tracks whether we have already emitted the BLAKE3 fallback warning so we
# don't spam the logs on every call.
_blake3_warned: bool = False


class TileHasher:
    """Hasher component for tile content.

    Computes and verifies hashes of tile data using the configured algorithm.
    """

    def __init__(self, algorithm: HashAlgorithm = HashAlgorithm.BLAKE3) -> None:
        self.algorithm = algorithm

    def hash(self, data: bytes) -> bytes:
        """Compute the hash digest of *data* using the configured algorithm.

        Parameters
        ----------
        data:
            Raw bytes to hash (typically a PNG tile).

        Returns
        -------
        bytes
            Raw digest bytes (not hex-encoded).

        Raises
        ------
        TileHashError
            If hashing fails.
        """
        return hash_bytes(data, self.algorithm)

    def verify(self, data: bytes, expected: bytes) -> bool:
        """Verify that the hash of *data* matches *expected*.

        Parameters
        ----------
        data:
            Raw bytes to hash and verify.
        expected:
            Expected digest bytes.

        Returns
        -------
        bool
            True if the computed hash matches the expected hash, False otherwise.
        """
        return self.hash(data) == expected


def hash_bytes(data: bytes, algorithm: HashAlgorithm = HashAlgorithm.BLAKE3) -> bytes:
    """Return the hash digest of *data* using *algorithm*.

    Parameters
    ----------
    data:
        Raw bytes to hash (typically a PNG tile).
    algorithm:
        Which algorithm to use.  Defaults to BLAKE3.

    Returns
    -------
    bytes
        Raw digest bytes (not hex-encoded).

    Raises
    ------
    TileHashError
        If hashing fails for reasons other than a missing ``blake3`` package.
    """
    global _blake3_warned

    if algorithm is HashAlgorithm.SHA256:
        # Explicit SHA-256 – no BLAKE3 involved at all.
        return _sha256(data)

    if algorithm is HashAlgorithm.BLAKE3:
        try:
            import blake3  # type: ignore[import]
            return blake3.blake3(data).digest()
        except ImportError:
            if not _blake3_warned:
                _log.warning(
                    "blake3 package not found; falling back to SHA-256. "
                    "Install it with: pip install blake3"
                )
                _blake3_warned = True
            return _sha256(data)
        except Exception as exc:
            raise TileHashError(f"BLAKE3 hashing failed: {exc}") from exc

    raise TileHashError(f"Unsupported hash algorithm: {algorithm!r}")


def _sha256(data: bytes) -> bytes:
    """Compute a SHA-256 digest.  Internal helper."""
    try:
        return hashlib.sha256(data).digest()
    except Exception as exc:
        raise TileHashError(f"SHA-256 hashing failed: {exc}") from exc

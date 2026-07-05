"""Configuration settings for the tile synchronizer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import HashAlgorithm


@dataclass(frozen=True)
class TileSynchronizerSettings:
    """Configuration settings for the tile synchronisation process.

    Parameters
    ----------
    output_root:
        Root directory where the tile files are saved.
    database_path:
        Path to the SQLite database file.
    timeout:
        HTTP timeout in seconds.
    hash_algorithm:
        Algorithm to use for tile hashing.
    """

    output_root: Path
    database_path: Path
    timeout: int = 10
    hash_algorithm: HashAlgorithm = HashAlgorithm.BLAKE3

"""Configuration settings for the tile synchronizer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

from .downloader import RetryPolicy
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
    scan_radius:
        Radius in tiles to scan around each player.
    base_url:
        Base URL of the Dynmap server.
    dynmap_config:
        The raw dictionary representation of the Dynmap configuration JSON.
    max_workers:
        Number of worker threads for parallel tile processing.
    retry_policy:
        HTTP request retry policy configuration.
    """

    output_root: Path
    database_path: Path
    timeout: int = 10
    hash_algorithm: HashAlgorithm = HashAlgorithm.BLAKE3
    scan_radius: int = 2
    base_url: str = ""
    dynmap_config: Dict[str, Any] = field(default_factory=dict)
    max_workers: Optional[int] = 4
    retry_policy: Optional[RetryPolicy] = field(default_factory=RetryPolicy)

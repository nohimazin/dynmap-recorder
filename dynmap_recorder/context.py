import dataclasses
from typing import Dict, Any


@dataclasses.dataclass(frozen=True)
class TickContext:
    """Immutable container passed to recorders and synchronizers on each poll tick.

    Attributes
    ----------
    timestamp: int
        Epoch milliseconds when the poll was performed.
    payload: Dict[str, Any]
        Raw JSON payload returned by the Dynmap API for this tick.
    player_cache: Dict[int, Dict[str, Any]]
        Mapping of player_id (int) to the most recent player state dict.
    world_id: int
        Integer id for the world being recorded (resolved via MetadataManager).
    interval: float
        Seconds between successive polls (configurable).
    metadata_manager: Any
        Reference to the shared MetadataManager instance (used by recorders to resolve ids).
    """

    timestamp: int
    payload: Dict[str, Any]
    player_cache: Dict[int, Dict[str, Any]]
    world_id: int
    interval: float
    metadata_manager: Any

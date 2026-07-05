import dataclasses
from typing import Dict, Any, Mapping, FrozenSet

from .metadata import MetadataManager
from .player_state import PlayerState


@dataclasses.dataclass(frozen=True)
class TickContext:
    """Immutable container passed to recorders and synchronizers on each poll tick.

    Attributes
    ----------
    timestamp: int
        Epoch milliseconds when the poll completed (after fetching data).
    started_at: int
        Epoch milliseconds when the poll started. Useful for measuring duration.
    tick: int
        Sequential poll number.
    interval: float
        Seconds between successive polls.
    payload: Dict[str, Any]
        Raw JSON payload returned by the Dynmap API for this tick.
    metadata: MetadataManager
        Shared ``MetadataManager`` instance (used by recorders to resolve IDs).
    world_id: int
        Integer ID for the world being recorded.
    player_cache: Mapping[int, PlayerState]
        Mapping of ``player_id`` to immutable ``PlayerState`` objects.
    changed_players: FrozenSet[int]
        Set of player IDs whose state changed this tick.
    joined_players: FrozenSet[int]
        Set of player IDs that joined this tick.
    quit_players: FrozenSet[int]
        Set of player IDs that quit this tick.
    """

    timestamp: int
    started_at: int
    tick: int
    interval: float
    payload: Dict[str, Any]
    metadata: MetadataManager
    world_id: int
    player_cache: Mapping[int, PlayerState]
    changed_players: FrozenSet[int]
    joined_players: FrozenSet[int]
    quit_players: FrozenSet[int]

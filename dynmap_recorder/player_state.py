from dataclasses import dataclass

@dataclass(frozen=True)
class PlayerState:
    """Immutable representation of a player's state at a tick.

    Attributes
    ----------
    player_id: int
        Unique identifier for the player (as assigned by MetadataManager).
    world_id: int
        World identifier where the player is located.
    x: float
        X coordinate.
    y: float
        Y coordinate.
    z: float
        Z coordinate.
    yaw: float
        Horizontal rotation angle.
    pitch: float
        Vertical rotation angle.
    hp: float
        Health points.
    armor: float
        Armor value.
    online: bool
        Whether the player is currently online.
    """

    player_id: int
    world_id: int
    x: float
    y: float
    z: float
    yaw: float
    pitch: float
    hp: float
    armor: float
    online: bool

"""Visible-tile scanner.

Phase 3 stub: returns an empty list.  The real algorithm (player-viewport
intersection, priority ordering, etc.) will be implemented in Phase 4.
"""

from __future__ import annotations

from typing import List

from .models import VisibleTile


class VisibleTileScanner:
    """Determine which tiles need to be checked during a tick.

    Phase 3 implementation always returns an empty list.  The
    :class:`~synchronizer.TileSynchronizer` loop simply skips when no tiles
    are returned.
    """

    def scan(self, ctx) -> List[VisibleTile]:  # type: ignore[type-arg]
        """Return tiles that should be synchronised for this tick.

        Parameters
        ----------
        ctx:
            The :class:`~dynmap_recorder.context.TickContext` for the current
            poll.  Not used in Phase 3.

        Returns
        -------
        List[VisibleTile]
            Always empty in Phase 3.
        """
        return []

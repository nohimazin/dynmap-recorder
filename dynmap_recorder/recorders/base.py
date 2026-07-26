from typing import Any

class BaseRecorder:
    """Base class for all recorders.

    Recorders now receive a single immutable ``TickContext`` object that
    bundles all information required for a poll tick.  Sub‑classes should
    implement ``on_tick`` and may optionally implement ``on_start`` and
    ``on_stop`` for lifecycle handling.
    """

    def on_start(self, config: dict, resolved_args: Any, metadata_manager: Any) -> None:
        """Called when the poller starts up, to initialize the recorder."""
        pass

    def on_tick(self, ctx: Any) -> None:
        """Called for each poll tick with a :class:`TickContext` instance.

        ``ctx`` provides ``timestamp``, ``payload``, ``player_cache``,
        ``world_id``, ``interval`` and ``metadata_manager``.
        """
        pass

    def on_stop(self) -> None:
        """Called when the poller is shutting down."""
        pass

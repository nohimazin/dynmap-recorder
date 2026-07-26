from argparse import Namespace
from pathlib import Path

from dynmap_recorder.metadata import MetadataManager
from dynmap_recorder.poller import DynmapPoller
from dynmap_recorder.synchronizers.tile.synchronizer import TileSynchronizer


def make_poller(tmp_path: Path, **overrides) -> DynmapPoller:
    values = {
        "output_dir": tmp_path / "outputs",
        "state_file": None,
        "interval": 2.0,
        "timeout": 15.0,
        "user_agent": "test-agent",
        "duration": 1.0,
        "timezone_offset": 0,
        "tile_recorder": False,
        "tile_scan_radius": 2,
        "tile_max_workers": 2,
        "tile_hash_algorithm": "sha256",
    }
    values.update(overrides)
    metadata = MetadataManager(values["output_dir"] / "metadata")
    return DynmapPoller(
        base_url="http://example.test",
        world="world",
        config={},
        resolved_args=Namespace(**values),
        metadata_manager=metadata,
    )


def test_build_tick_context_contains_tile_player_state(tmp_path):
    poller = make_poller(tmp_path)

    ctx = poller._build_tick_context(
        {
            "players": [
                {
                    "account": "Alex",
                    "world": "world",
                    "x": 12,
                    "y": 64,
                    "z": -3,
                    "health": 18,
                    "armor": 5,
                }
            ]
        },
        timestamp=1234,
        started_at=1200,
    )

    assert ctx.tick == 1
    assert ctx.world_id == poller.metadata_manager.get_world_id("world")
    state = next(iter(ctx.player_cache.values()))
    assert state.x == 12.0
    assert state.y == 64.0
    assert state.z == -3.0
    assert ctx.player_coords_cache["Alex"]["x"] == 12


def test_tile_recorder_is_created_from_server_config(tmp_path):
    poller = make_poller(tmp_path, tile_recorder=True)

    poller._register_tile_recorder(
        {
            "worlds": [
                {
                    "name": "world",
                    "maps": [{"name": "flat", "prefix": "flat", "maxzoom": 1}],
                }
            ]
        }
    )

    assert len(poller.recorders) == 1
    assert isinstance(poller.recorders[0], TileSynchronizer)
    assert poller.recorders[0].scanner.dynmap_config["worlds"][0]["name"] == "world"
    poller.recorders[0].on_stop()


def test_poller_start_recovers_from_configuration_timeout_and_delivers_ticks(tmp_path, monkeypatch):
    poller = make_poller(tmp_path, duration=1.0, interval=0.1)
    events = []

    class Recorder:
        def on_start(self, config, resolved_args, metadata_manager):
            events.append(("start", config))

        def on_tick(self, ctx):
            events.append(("tick", ctx))

        def on_stop(self):
            events.append(("stop",))

    poller.register_recorder(Recorder())
    responses = iter(
        [
            TimeoutError("configuration timeout"),
            {"defaultworld": "world", "updaterate": 100},
            {"timestamp": 1000, "players": [{"account": "Alex", "world": "world", "x": 1}]},
            {"timestamp": 1100, "players": [{"account": "Alex", "world": "world", "x": 2}]},
        ]
    )

    def fake_fetch_json(*args, **kwargs):
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    # start(), retry checks, initial fetch, loop check, then stop check.
    monotonic_values = iter([0.0, 0.0, 0.0, 0.0, 0.0, 2.0])
    monkeypatch.setattr("dynmap_recorder.poller.fetch_json", fake_fetch_json)
    monkeypatch.setattr("dynmap_recorder.poller.time.monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr("dynmap_recorder.poller.time.sleep", lambda _: None)

    assert poller.start() == 0
    assert [event[0] for event in events] == ["start", "tick", "tick", "stop"]
    first_ctx = events[1][1]
    second_ctx = events[2][1]
    assert first_ctx.joined_players
    assert second_ctx.changed_players
    assert first_ctx.player_cache[next(iter(first_ctx.player_cache))].x == 1.0
    assert second_ctx.player_cache[next(iter(second_ctx.player_cache))].x == 2.0

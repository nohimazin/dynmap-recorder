import argparse
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from pathlib import Path
from typing import Any, List

from dynmap_recorder.metadata import MetadataManager
from dynmap_recorder.recorders.base import BaseRecorder
from dynmap_recorder.context import TickContext
from dynmap_recorder.player_state import PlayerState
from dynmap_recorder.synchronizers.tile import TileSynchronizerSettings, create_default_synchronizer
from dynmap_recorder.synchronizers.tile.models import HashAlgorithm


def fetch_json(url: str, timeout: float = 15.0, user_agent: str = "dynmap-public-collector/1.0") -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": user_agent})
    with urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return json.loads(response.read().decode(charset))


class DynmapPoller:
    def __init__(
        self,
        base_url: str,
        world: str | None,
        config: dict,
        resolved_args: argparse.Namespace,
        metadata_manager: MetadataManager,
    ):
        self.base_url = base_url.rstrip("/")
        self.config_obj = config
        self.args = resolved_args
        self.metadata_manager = metadata_manager
        
        self.output_dir = Path(getattr(resolved_args, "output_dir", "outputs"))
        self.state_file = self.output_dir / "state" / "dynmap_state.json"
        
        # Support migration from legacy state file path
        self.legacy_state_file = getattr(resolved_args, "state_file", None)
        if self.legacy_state_file and not isinstance(self.legacy_state_file, Path):
            self.legacy_state_file = Path(self.legacy_state_file)
        
        self.recorders: List[BaseRecorder] = []
        self.player_coords_cache: dict[str, dict[str, Any]] = {}
        
        self.world = world
        self.interval = getattr(resolved_args, "interval", None)
        self.timeout = getattr(resolved_args, "timeout", 15.0) or 15.0
        self.user_agent = getattr(resolved_args, "user_agent", "dynmap-public-collector/1.0") or "dynmap-public-collector/1.0"
        self.duration = getattr(resolved_args, "duration", 0.0) or 0.0
        self.timezone_offset = getattr(resolved_args, "timezone_offset", 0) or 0
        self.target_tz = timezone(timedelta(hours=self.timezone_offset))
        self.tick = 0

    def register_recorder(self, recorder: BaseRecorder) -> None:
        self.recorders.append(recorder)

    def _register_tile_recorder(self, dynmap_config: dict[str, Any]) -> None:
        """Create the tile synchronizer after the server map config is known."""
        if not getattr(self.args, "tile_recorder", False):
            return

        output_root = self.output_dir / "tiles"
        settings = TileSynchronizerSettings(
            output_root=output_root,
            database_path=output_root / "tiles.db",
            timeout=int(self.timeout),
            scan_radius=int(getattr(self.args, "tile_scan_radius", 2) or 2),
            base_url=self.base_url,
            dynmap_config=dynmap_config,
            max_workers=int(getattr(self.args, "tile_max_workers", 4) or 4),
            hash_algorithm=HashAlgorithm(getattr(self.args, "tile_hash_algorithm", "blake3")),
        )
        self.recorders.append(create_default_synchronizer(settings))

    def _build_tick_context(self, payload: dict[str, Any], timestamp: int, started_at: int) -> TickContext:
        """Build the immutable context shared by all recorders."""
        self._update_coords_cache(payload)
        player_states: dict[int, PlayerState] = {}
        for entry in payload.get("players", []):
            name = entry.get("account") or entry.get("name")
            if not name:
                continue
            player_id = self.metadata_manager.get_player_id(str(name))
            world_name = entry.get("world") or self.world or "world"
            world_id = self.metadata_manager.get_world_id(str(world_name))

            def number(key: str) -> float:
                value = entry.get(key)
                try:
                    return float(value) if value is not None else 0.0
                except (TypeError, ValueError):
                    return 0.0

            player_states[player_id] = PlayerState(
                player_id=player_id,
                world_id=world_id,
                x=number("x"),
                y=number("y"),
                z=number("z"),
                yaw=number("yaw"),
                pitch=number("pitch"),
                hp=number("health"),
                armor=number("armor"),
                online=True,
            )

        world_id = self.metadata_manager.get_world_id(self.world or "world")
        current_player_ids = frozenset(player_states)
        previous_player_ids = getattr(self, "_previous_player_ids", frozenset())
        changed_players = frozenset(
            player_id
            for player_id in current_player_ids & previous_player_ids
            if player_states[player_id] != self._previous_player_states.get(player_id)
        ) if hasattr(self, "_previous_player_states") else frozenset()
        joined_players = current_player_ids - previous_player_ids
        quit_players = previous_player_ids - current_player_ids
        self._previous_player_ids = current_player_ids
        self._previous_player_states = player_states
        self.tick += 1
        return TickContext(
            timestamp=timestamp,
            started_at=started_at,
            tick=self.tick,
            interval=float(self.interval or 0.0),
            payload=payload,
            metadata=self.metadata_manager,
            world_id=world_id,
            player_cache=player_states,
            player_coords_cache=self.player_coords_cache,
            changed_players=changed_players,
            joined_players=joined_players,
            quit_players=quit_players,
        )

    def _now_iso(self) -> str:
        return datetime.now(self.target_tz).isoformat()

    def _read_state(self) -> dict[str, Any]:
        path = self.state_file
        if not path.exists() and self.legacy_state_file and self.legacy_state_file.exists():
            path = self.legacy_state_file
            
        if not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"state read failed ({path}): {exc}", file=sys.stderr)
            return {}
        return data if isinstance(data, dict) else {}

    def _write_state(self, timestamp: int) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "base": self.base_url,
            "world": self.world,
            "timestamp": timestamp,
            "saved_at": self._now_iso(),
        }
        tmp_path = self.state_file.with_suffix(".tmp")
        try:
            with tmp_path.open("w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
            tmp_path.replace(self.state_file)
            if self.legacy_state_file and self.legacy_state_file.exists() and self.legacy_state_file != self.state_file:
                try:
                    self.legacy_state_file.unlink()
                except Exception:
                    pass
        except Exception as e:
            print(f"Error saving state file: {e}", file=sys.stderr)
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass

    def _state_timestamp(self) -> int:
        if getattr(self.args, "since", None) is not None:
            return int(self.args.since)
        state = self._read_state()
        if state.get("base") == self.base_url and state.get("world") == self.world:
            try:
                return int(state.get("timestamp", 0))
            except (TypeError, ValueError):
                return 0
        return 0

    def _update_coords_cache(self, p_payload: dict[str, Any]) -> None:
        for p in p_payload.get("players", []):
            name = p.get("account") or p.get("name")
            if name:
                self.player_coords_cache[str(name)] = {
                    "world": p.get("world"),
                    "x": p.get("x"),
                    "y": p.get("y"),
                    "z": p.get("z"),
                    "health": p.get("health"),
                    "armor": p.get("armor"),
                }
        if len(self.player_coords_cache) > 10000:
            curr_names = set()
            for player in p_payload.get("players", []):
                name = player.get("account") or player.get("name")
                if name:
                    curr_names.add(str(name))
            for name in list(self.player_coords_cache.keys()):
                if name not in curr_names:
                    self.player_coords_cache.pop(name, None)

    def _should_stop(self, deadline: float | None) -> bool:
        return deadline is not None and time.monotonic() >= deadline

    def _fetch_json_retry(
        self,
        url: str,
        deadline: float | None,
        label: str,
        retry_interval: float = 1.0,
    ) -> dict[str, Any] | None:
        failures = 0
        while True:
            if self._should_stop(deadline):
                return None
            try:
                return fetch_json(url, timeout=self.timeout, user_agent=self.user_agent)
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
                failures += 1
                backoff = min(retry_interval * (failures + 1), 30.0)
                print(f"{label} failed: {exc}", file=sys.stderr)
                time.sleep(backoff)

    def start(self) -> int:
        deadline = time.monotonic() + self.duration if self.duration else None

        config = self._fetch_json_retry(f"{self.base_url}/up/configuration", deadline, "configuration fetch")
        if config is None:
            return 0

        if not self.world:
            self.world = config.get("defaultworld") or "world"
        if not self.interval:
            self.interval = max(float(config.get("updaterate", 1000.0)) / 1000.0, 1.0)

        self._register_tile_recorder(config)

        print(
            f"base={self.base_url} world={self.world} interval={self.interval:.1f}s "
            f"chat_enabled={config.get('allowchat')} webchat_enabled={config.get('allowwebchat')}",
            file=sys.stderr,
        )

        for recorder in self.recorders:
            recorder.on_start(self.config_obj, self.args, self.metadata_manager)

        timestamp = self._state_timestamp()
        initial_payload = self._fetch_json_retry(
            f"{self.base_url}/up/world/{self.world}/{timestamp}",
            deadline,
            "initial update fetch",
            self.interval,
        )
        if initial_payload is None:
            return 0

        self._update_coords_cache(initial_payload)
        timestamp = int(initial_payload.get("timestamp", timestamp))
        self._write_state(timestamp)

        initial_started_at = int(time.time() * 1000)
        initial_ctx = self._build_tick_context(initial_payload, timestamp, initial_started_at)
        for recorder in self.recorders:
            recorder.on_tick(initial_ctx)

        consecutive_failures = 0
        try:
            while True:
                if self._should_stop(deadline):
                    self._write_state(timestamp)
                    break

                time.sleep(self.interval)
                try:
                    payload = fetch_json(
                        f"{self.base_url}/up/world/{self.world}/{timestamp}",
                        timeout=self.timeout,
                        user_agent=self.user_agent,
                    )
                except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
                    consecutive_failures += 1
                    backoff = min(self.interval * (consecutive_failures + 1), 30.0)
                    print(f"poll failed: {exc}", file=sys.stderr)
                    time.sleep(backoff)
                    continue

                consecutive_failures = 0
                timestamp = int(payload.get("timestamp", timestamp))
                self._write_state(timestamp)

                self._update_coords_cache(payload)

                started_at = int(time.time() * 1000)
                ctx = self._build_tick_context(payload, timestamp, started_at)
                for recorder in self.recorders:
                    recorder.on_tick(ctx)

        except KeyboardInterrupt:
            print("interrupted; latest state has been saved", file=sys.stderr)
            self._write_state(timestamp)
            return 130
        finally:
            for recorder in self.recorders:
                recorder.on_stop()

        return 0

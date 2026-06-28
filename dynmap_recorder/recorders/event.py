import csv
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from dynmap_recorder.recorders.base import BaseRecorder

EVENT_TYPES = {
    "chat",
    "webchat",
    "playerjoin",
    "playerquit",
}

CSV_FIELDS = [
    "collected_at",
    "event_time",
    "timestamp",
    "type",
    "source",
    "player",
    "message",
    "world",
    "x",
    "y",
    "z",
    "health",
    "armor",
]


class EventRecorder(BaseRecorder):
    def on_start(self, config: dict, resolved_args: Any, metadata_manager: Any) -> None:
        self.config = config
        self.args = resolved_args
        self.metadata_manager = metadata_manager
        
        self.output_dir = Path(getattr(resolved_args, "output_dir", "outputs"))
        self.verbose = getattr(resolved_args, "verbose", False)
        self.infer_events = getattr(resolved_args, "infer_player_events", False)
        
        self.tz_offset = getattr(resolved_args, "timezone_offset", 0)
        self.target_tz = timezone(timedelta(hours=self.tz_offset))

        self.custom_jsonl_output = getattr(resolved_args, "jsonl_output", None)
        self.custom_csv_output = getattr(resolved_args, "csv_output", None)
        
        self.first_poll = True
        self.previous_players = set()


    def _get_timezone(self) -> timezone:
        return self.target_tz

    def _now_iso(self) -> str:
        return datetime.now(self._get_timezone()).isoformat()

    def _timestamp_to_iso(self, timestamp: Any) -> str:
        if timestamp is None:
            return ""
        try:
            value = float(timestamp)
        except (TypeError, ValueError):
            return ""
        if value > 10_000_000_000:
            value /= 1000.0
        return datetime.fromtimestamp(value, timezone.utc).astimezone(self._get_timezone()).isoformat()

    def _get_target_paths(self) -> tuple[Path, Path]:
        jsonl_path = self.custom_jsonl_output or (self.output_dir / "dynmap_events.jsonl")
        csv_path = self.custom_csv_output or (self.output_dir / "dynmap_events.csv")
        return jsonl_path, csv_path

    def _write_jsonl(self, path: Path, record: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def _write_csv(self, path: Path, record: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not path.exists() or path.stat().st_size == 0
        with path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
            if write_header:
                writer.writeheader()
            writer.writerow({field: record.get(field, "") for field in CSV_FIELDS})

    def normalize_event(
        self,
        raw: dict[str, Any],
        source: str = "dynmap-update",
        player_coords_cache: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        collected_at = self._now_iso()
        player = (
            raw.get("playerName")
            or raw.get("player")
            or raw.get("account")
            or raw.get("username")
            or raw.get("name")
            or raw.get("displayName")
            or raw.get("author_name")
            or (raw.get("author") if isinstance(raw.get("author"), str) else None)
            or (raw.get("author", {}) or {}).get("username")
            or (raw.get("author", {}) or {}).get("name")
            or (raw.get("author", {}) or {}).get("displayName")
        )
        if not player:
            channel = raw.get("channel")
            if isinstance(channel, str):
                parts = channel.split("]")
                if len(parts) > 1:
                    candidate = parts[1].strip()
                    if candidate:
                        player = candidate
                else:
                    tokens = channel.strip().split()
                    if tokens:
                        player = tokens[-1]
        
        world = raw.get("world")
        x = raw.get("x")
        y = raw.get("y")
        z = raw.get("z")
        health = raw.get("health")
        armor = raw.get("armor")
        
        if player and player_coords_cache and player in player_coords_cache:
            coords = player_coords_cache[player]
            if world is None:
                world = coords.get("world")
            if x is None:
                x = coords.get("x")
            if y is None:
                y = coords.get("y")
            if z is None:
                z = coords.get("z")
            if health is None:
                health = coords.get("health")
            if armor is None:
                armor = coords.get("armor")

        if raw.get("source") == "plugin":
            source = "discord"
        
        return {
            "collected_at": collected_at,
            "event_time": self._timestamp_to_iso(raw.get("timestamp")),
            "timestamp": raw.get("timestamp"),
            "type": raw.get("type"),
            "source": source,
            "player": player,
            "message": raw.get("message"),
            "world": world,
            "x": x,
            "y": y,
            "z": z,
            "health": health,
            "armor": armor,
        }

    def infer_player_event(
        self,
        event_type: str,
        name: str,
        ctx: Any,
    ) -> dict[str, Any]:
        world = ""
        x = ""
        y = ""
        z = ""
        health = ""
        armor = ""

        if player_coords_cache and name in player_coords_cache:
            coords = player_coords_cache[name]
            world = coords.get("world", "")
            if world is None:
                world = ""
            x = coords.get("x", "")
            if x is None:
                x = ""
            y = coords.get("y", "")
            if y is None:
                y = ""
            z = coords.get("z", "")
            if z is None:
                z = ""
            health = coords.get("health", "")
            if health is None:
                health = ""
            armor = coords.get("armor", "")
            if armor is None:
                armor = ""

        return {
            "collected_at": self._now_iso(),
            "event_time": self._timestamp_to_iso(timestamp),
            "source": "player-list-diff",
            "type": event_type,
            "timestamp": timestamp,
            "player": name,
            "message": "",
            "world": world,
            "x": x,
            "y": y,
            "z": z,
            "health": health,
            "armor": armor,
        }

    def write_event(self, record: dict[str, Any]) -> None:
        jsonl_path, csv_path = self._get_target_paths()
        self._write_jsonl(jsonl_path, record)
        if csv_path:
            self._write_csv(csv_path, record)
            
        if self.verbose:
            player = record.get("player") or "-"
            message = record.get("message") or ""
            x = record.get("x")
            y = record.get("y")
            z = record.get("z")
            health = record.get("health")
            armor = record.get("armor")

            if x is not None and y is not None and z is not None and x != "" and y != "" and z != "":
                try:
                    pos_str = f" pos=({int(round(float(x)))},{int(round(float(y)))},{int(round(float(z)))})"
                except (ValueError, TypeError):
                    pos_str = f" pos=({x},{y},{z})"
            else:
                pos_str = ""

            hp_str = ""
            if health is not None and health != "":
                try:
                    h_val = float(health)
                    if h_val.is_integer():
                        hp_str = f" hp={int(h_val)}"
                    else:
                        hp_str = f" hp={h_val:.1f}"
                except (ValueError, TypeError):
                    hp_str = f" hp={health}"

            armor_str = ""
            if armor is not None and armor != "":
                try:
                    a_val = float(armor)
                    if a_val.is_integer():
                        armor_str = f" armor={int(a_val)}"
                    else:
                        armor_str = f" armor={a_val}"
                except (ValueError, TypeError):
                    armor_str = f" armor={armor}"

            source_str = f" source={record.get('source')}" if record.get('source') else ""
            print(f"{record.get('type')}{source_str} player={player}{pos_str}{hp_str}{armor_str} message={message}", file=sys.stderr)

    def on_tick(self, ctx: Any) -> None:
        """Handle a poll tick using TickContext.

        Args:
            ctx: TickContext containing timestamp, payload, player_cache, etc.
        """
        payload = ctx.payload
        timestamp = ctx.timestamp
        player_coords_cache = ctx.player_cache
        current_players = set()
        for player_entry in payload.get("players", []):
            name = player_entry.get("account") or player_entry.get("name")
            if name:
                current_players.add(str(name))

        if self.first_poll:
            self.previous_players = current_players
            self.first_poll = False
            if getattr(self.args, "snapshot", False):
                jsonl_path, _ = self._get_target_paths()
                self._write_jsonl(
                    jsonl_path,
                    {
                        "collected_at": self._now_iso(),
                        "source": "initial-snapshot",
                        "type": "players",
                        "timestamp": timestamp,
                        "players": sorted(current_players),
                        "raw": payload,
                    },
                )
            return

        joined_players_this_tick = set()
        quit_players_this_tick = set()

        if self.infer_events:
            for name in sorted((current_players - self.previous_players) - joined_players_this_tick):
                record = self.infer_player_event("playerjoin_inferred", name, timestamp, player_coords_cache=player_coords_cache)
                self.write_event(record)
            for name in sorted((self.previous_players - current_players) - quit_players_this_tick):
                record = self.infer_player_event("playerquit_inferred", name, timestamp, player_coords_cache=player_coords_cache)
                self.write_event(record)

        self.previous_players = current_players
        current_players = set()
        for player_entry in payload.get("players", []):
            name = player_entry.get("account") or player_entry.get("name")
            if name:
                current_players.add(str(name))

        if self.first_poll:
            self.previous_players = current_players
            self.first_poll = False
            if getattr(self.args, "snapshot", False):
                jsonl_path, _ = self._get_target_paths()
                self._write_jsonl(
                    jsonl_path,
                    {
                        "collected_at": self._now_iso(),
                        "source": "initial-snapshot",
                        "type": "players",
                        "timestamp": timestamp,
                        "players": sorted(current_players),
                        "raw": payload,
                    },
                )
            return

        joined_players_this_tick = set()
        quit_players_this_tick = set()

        if self.infer_events:
            for name in sorted((current_players - self.previous_players) - joined_players_this_tick):
                record = self.infer_player_event("playerjoin_inferred", name, timestamp, player_coords_cache=player_coords_cache)
                self.write_event(record)
            for name in sorted((self.previous_players - current_players) - quit_players_this_tick):
                record = self.infer_player_event("playerquit_inferred", name, timestamp, player_coords_cache=player_coords_cache)
                self.write_event(record)

        self.previous_players = current_players

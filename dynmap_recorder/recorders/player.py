import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from dynmap_recorder.recorders.base import BaseRecorder


def parse_number(val: Any) -> Any:
    if val is None or val == "":
        return None
    try:
        f_val = float(val)
        if f_val.is_integer():
            return int(f_val)
        return f_val
    except (ValueError, TypeError):
        return val


class PlayerRecorder(BaseRecorder):
    def on_start(self, config: dict, resolved_args: Any, metadata_manager: Any) -> None:
        self.config = config
        self.args = resolved_args
        self.metadata_manager = metadata_manager
        
        self.output_dir = Path(getattr(resolved_args, "output_dir", "outputs"))
        self.players_dir = self.output_dir / "recorder" / "players"
        
        self.tz_offset = getattr(resolved_args, "timezone_offset", 0)
        self.target_tz = timezone(timedelta(hours=self.tz_offset))

        # Memory cache of last recorded state: player_id -> state_dict
        self.last_saved_state = {}

    def _get_target_path(self, timestamp: int) -> Path:
        try:
            val = float(timestamp)
            if val > 10_000_000_000:
                val /= 1000.0
            dt = datetime.fromtimestamp(val, self.target_tz)
            date_str = dt.strftime("%Y-%m-%d")
        except Exception:
            date_str = datetime.now(self.target_tz).strftime("%Y-%m-%d")

        return self.players_dir / f"{date_str}.jsonl"

    def _write_jsonl(self, path: Path, record: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        ordered_record = {}
        for key in ["t", "p", "w", "x", "y", "z", "hp", "armor", "yaw", "pitch", "o"]:
            if key in record and record[key] is not None:
                ordered_record[key] = record[key]
                
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(ordered_record, ensure_ascii=False) + "\n")

    def on_tick(self, ctx: Any) -> None:
        """Handle a poll tick using TickContext.

        Args:
            ctx: TickContext containing timestamp, payload, player_cache, etc.
        """
        payload = ctx.payload
        timestamp = ctx.timestamp
        player_coords_cache = ctx.player_cache
        current_online_pids = set()

        for player_entry in payload.get("players", []):
            name = player_entry.get("account") or player_entry.get("name")
            if not name:
                continue
            name_str = str(name)

            world = player_entry.get("world") or "world"
            x = player_entry.get("x")
            y = player_entry.get("y")
            z = player_entry.get("z")
            health = player_entry.get("health")
            armor = player_entry.get("armor")
            yaw = player_entry.get("yaw")
            pitch = player_entry.get("pitch")

            # Map to IDs
            player_id = self.metadata_manager.get_player_id(name_str)
            world_id = self.metadata_manager.get_world_id(world)
            current_online_pids.add(player_id)

            current_state = {
                "w": world_id,
                "x": parse_number(x),
                "y": parse_number(y),
                "z": parse_number(z),
                "hp": parse_number(health),
                "armor": parse_number(armor),
                "yaw": parse_number(yaw),
                "pitch": parse_number(pitch),
                "o": True,
            }

            # Check if state changed (or player was offline/not in cache)
            last_state = self.last_saved_state.get(player_id)
            if last_state is None or last_state != current_state:
                # Write state record
                record = {
                    "t": timestamp,
                    "p": player_id,
                    **current_state,
                }
                path = self._get_target_path(timestamp)
                self._write_jsonl(path, record)
                # Update cache
                self.last_saved_state[player_id] = current_state

        # Check for players who went offline
        for player_id, last_state in list(self.last_saved_state.items()):
            if last_state.get("o") is True and player_id not in current_online_pids:
                # Write offline record
                record = {
                    "t": timestamp,
                    "p": player_id,
                    "o": False,
                }
                path = self._get_target_path(timestamp)
                self._write_jsonl(path, record)
                # Update cache to offline state
                self.last_saved_state[player_id] = {"o": False}
        current_online_pids = set()

        for player_entry in payload.get("players", []):
            name = player_entry.get("account") or player_entry.get("name")
            if not name:
                continue
            name_str = str(name)
            
            world = player_entry.get("world") or "world"
            x = player_entry.get("x")
            y = player_entry.get("y")
            z = player_entry.get("z")
            health = player_entry.get("health")
            armor = player_entry.get("armor")
            yaw = player_entry.get("yaw")
            pitch = player_entry.get("pitch")

            # Map to IDs
            player_id = self.metadata_manager.get_player_id(name_str)
            world_id = self.metadata_manager.get_world_id(world)
            current_online_pids.add(player_id)

            current_state = {
                "w": world_id,
                "x": parse_number(x),
                "y": parse_number(y),
                "z": parse_number(z),
                "hp": parse_number(health),
                "armor": parse_number(armor),
                "yaw": parse_number(yaw),
                "pitch": parse_number(pitch),
                "o": True
            }

            # Check if state changed (or player was offline/not in cache)
            last_state = self.last_saved_state.get(player_id)
            if last_state is None or last_state != current_state:
                # Write state record
                record = {
                    "t": timestamp,
                    "p": player_id,
                    **current_state
                }
                
                path = self._get_target_path(timestamp)
                self._write_jsonl(path, record)
                
                # Update cache
                self.last_saved_state[player_id] = current_state

        # Check for players who went offline
        for player_id, last_state in list(self.last_saved_state.items()):
            if last_state.get("o") is True and player_id not in current_online_pids:
                # Write offline record
                record = {
                    "t": timestamp,
                    "p": player_id,
                    "o": False
                }
                path = self._get_target_path(timestamp)
                self._write_jsonl(path, record)
                
                # Update cache to offline state
                self.last_saved_state[player_id] = {"o": False}

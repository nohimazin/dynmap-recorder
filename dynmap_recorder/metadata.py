import json
import sys
from pathlib import Path


class MetadataManager:
    def __init__(self, metadata_dir: Path):
        self.metadata_dir = metadata_dir
        self.players_file = metadata_dir / "players.json"
        self.worlds_file = metadata_dir / "worlds.json"
        self.schema_file = metadata_dir / "schema.json"
        
        self.players_by_id = {}
        self.players_by_name = {}
        self.worlds_by_id = {}
        self.worlds_by_name = {}
        
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        self._load_all()
        self._ensure_schema()

    def _load_all(self):
        # Load players
        if self.players_file.exists():
            try:
                with self.players_file.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        for k, v in data.items():
                            name = str(v)
                            try:
                                pid = int(k)
                            except ValueError:
                                continue
                            self.players_by_id[pid] = name
                            self.players_by_name[name] = pid
            except Exception as e:
                print(f"Error loading players.json: {e}", file=sys.stderr)

        # Load worlds
        if self.worlds_file.exists():
            try:
                with self.worlds_file.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        for k, v in data.items():
                            wname = str(v)
                            try:
                                wid = int(k)
                            except ValueError:
                                continue
                            self.worlds_by_id[wid] = wname
                            self.worlds_by_name[wname] = wid
            except Exception as e:
                print(f"Error loading worlds.json: {e}", file=sys.stderr)

    def _ensure_schema(self):
        if not self.schema_file.exists():
            self._save_json(self.schema_file, {"version": 1})

    def _save_json(self, path: Path, data: dict):
        tmp_path = path.with_suffix(".tmp")
        try:
            with tmp_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
                f.write("\n")
            tmp_path.replace(path)
        except Exception as e:
            print(f"Error saving to {path}: {e}", file=sys.stderr)
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass

    def get_player_id(self, name: str) -> int:
        if name in self.players_by_name:
            return self.players_by_name[name]
        
        new_id = max(self.players_by_id.keys()) + 1 if self.players_by_id else 0
        self.players_by_id[new_id] = name
        self.players_by_name[name] = new_id
        
        to_save = {str(k): v for k, v in sorted(self.players_by_id.items())}
        self._save_json(self.players_file, to_save)
        
        return new_id

    def get_world_id(self, name: str) -> int:
        if name in self.worlds_by_name:
            return self.worlds_by_name[name]
        
        new_id = max(self.worlds_by_id.keys()) + 1 if self.worlds_by_id else 0
        self.worlds_by_id[new_id] = name
        self.worlds_by_name[name] = new_id
        
        to_save = {str(k): v for k, v in sorted(self.worlds_by_id.items())}
        self._save_json(self.worlds_file, to_save)
        
        return new_id

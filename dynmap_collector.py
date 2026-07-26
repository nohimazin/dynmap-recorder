from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from dynmap_recorder.metadata import MetadataManager
from dynmap_recorder.poller import DynmapPoller
from dynmap_recorder.recorders.event import EventRecorder
from dynmap_recorder.recorders.player import PlayerRecorder


def load_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        default_config = {
            "base": None,
            "world": None,
            "interval": None,
            "duration": 0.0,
            "timeout": 15.0,
            "jsonl_output": None,
            "csv_output": None,
            "state_file": None,
            "output_dir": "outputs",
            "snapshot": False,
            "infer_player_events": False,
            "verbose": False,
            "user_agent": "dynmap-public-collector/1.0",
            "timezone_offset": 0,
            "event_recorder": True,
            "player_recorder": True,
            "tile_recorder": False,
            "tile_scan_radius": 2,
            "tile_max_workers": 4,
            "tile_hash_algorithm": "blake3",
        }
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with config_path.open("w", encoding="utf-8") as handle:
                json.dump(default_config, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            print(f"Created a default configuration file template at {config_path}", file=sys.stderr)
            return default_config
        except Exception as exc:
            print(f"Warning: Failed to create default config at {config_path}: {exc}", file=sys.stderr)
            return {}
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
            if isinstance(data, dict):
                return data
    except Exception as exc:
        print(f"Warning: Failed to load config from {config_path}: {exc}", file=sys.stderr)
    return {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dynmap/LiveAtlas Data Recorder CLI")
    parser.add_argument("--config", default=None, help="Path to config JSON file")
    parser.add_argument("--base", default=None, help="Dynmap/LiveAtlas base URL")
    parser.add_argument("--world", default=None, help="Dynmap world name; defaults to configuration.defaultworld")
    parser.add_argument(
        "--since",
        type=int,
        default=None,
        help="Dynmap update timestamp to start from; overrides state file",
    )
    parser.add_argument("--interval", type=float, default=None, help="Polling interval in seconds")
    parser.add_argument("--duration", type=float, default=None, help="Stop after N seconds; 0 means run forever")
    parser.add_argument("--timeout", type=float, default=None, help="HTTP timeout in seconds")
    
    parser.add_argument("--jsonl-output", type=Path, default=None, help="JSONL output path (legacy/custom)")
    parser.add_argument("--csv-output", type=Path, default=None, help="CSV output path (legacy/custom)")
    parser.add_argument("--state-file", type=Path, default=None, help="Poll state JSON path (legacy/custom)")
    
    parser.add_argument("--output-dir", type=Path, default=None, help="Output root directory")
    
    parser.add_argument("--snapshot", action="store_true", default=None, help="Write initial player/update snapshot")
    parser.add_argument(
        "--infer-player-events",
        action="store_true",
        default=None,
        help="Infer joins/quits from changes in the public player list",
    )
    parser.add_argument("--verbose", action="store_true", default=None, help="Print collected events to stderr")
    parser.add_argument("--user-agent", default=None, help="HTTP User-Agent header")
    parser.add_argument("--timezone-offset", type=int, default=None, help="Hours offset from UTC for timestamps")

    parser.add_argument("--event-recorder", action="store_true", default=None, help="Enable Event Recorder")
    parser.add_argument("--no-event-recorder", action="store_false", dest="event_recorder", help="Disable Event Recorder")
    
    parser.add_argument("--player-recorder", action="store_true", default=None, help="Enable Player Recorder")
    parser.add_argument("--no-player-recorder", action="store_false", dest="player_recorder", help="Disable Player Recorder")
    parser.add_argument("--tile-recorder", action="store_true", default=None, help="Enable tile recorder")
    parser.add_argument("--no-tile-recorder", action="store_false", dest="tile_recorder", help="Disable tile recorder")
    parser.add_argument("--tile-scan-radius", type=int, default=None, help="Tile scan radius around players")
    parser.add_argument("--tile-max-workers", type=int, default=None, help="Tile download worker count")
    parser.add_argument("--tile-hash-algorithm", choices=("blake3", "sha256"), default=None, help="Tile hash algorithm")

    args = parser.parse_args()

    # Determine config file path
    script_dir = Path(__file__).resolve().parent
    config_path = Path(args.config) if args.config else script_dir / "config.json"

    config = load_config(config_path)

    defaults = {
        "base": None,
        "world": None,
        "since": None,
        "interval": None,
        "duration": 0.0,
        "timeout": 15.0,
        "jsonl_output": None,
        "csv_output": None,
        "state_file": None,
        "output_dir": Path("outputs"),
        "snapshot": False,
        "infer_player_events": False,
        "verbose": False,
        "user_agent": "dynmap-public-collector/1.0",
        "timezone_offset": 0,
        "event_recorder": True,
        "player_recorder": True,
        "tile_recorder": False,
        "tile_scan_radius": 2,
        "tile_max_workers": 4,
        "tile_hash_algorithm": "blake3",
    }

    resolved = argparse.Namespace()
    resolved.config = config_path

    path_keys = {"jsonl_output", "csv_output", "state_file", "output_dir"}

    for key, val in defaults.items():
        cli_val = getattr(args, key, None)
        if cli_val is not None:
            setattr(resolved, key, cli_val)
        elif key in config:
            config_val = config[key]
            if key in path_keys and config_val is not None:
                config_val = Path(config_val)
            setattr(resolved, key, config_val)
        else:
            setattr(resolved, key, val)

    # Validate that base URL is specified
    if not resolved.base:
        parser.print_usage(sys.stderr)
        print("Error: --base URL must be specified either in the config file or as a command line argument.", file=sys.stderr)
        sys.exit(1)

    return resolved


def main() -> int:
    resolved_args = parse_args()

    if resolved_args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    # Create metadata manager in outputs/metadata/
    output_dir = Path(resolved_args.output_dir)
    metadata_dir = output_dir / "metadata"
    metadata_manager = MetadataManager(metadata_dir)

    # Instantiate poller
    poller = DynmapPoller(
        base_url=resolved_args.base,
        world=resolved_args.world,
        config=load_config(resolved_args.config),
        resolved_args=resolved_args,
        metadata_manager=metadata_manager,
    )

    event_enabled = resolved_args.event_recorder
    player_enabled = resolved_args.player_recorder

    # Register active recorders
    if event_enabled:
        poller.register_recorder(EventRecorder())
    if player_enabled:
        poller.register_recorder(PlayerRecorder())

    return poller.start()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("interrupted; latest state has been saved", file=sys.stderr)
        sys.exit(130)

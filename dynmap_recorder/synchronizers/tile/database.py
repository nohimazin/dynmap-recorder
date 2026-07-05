"""SQLite‑backed metadata store for tiles.

The metadata store tracks hash, size, ETag, and timestamps for each tile.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Optional

from .models import TileID, TileState


class TileDatabase:
    """SQLite database wrapper for managing tile metadata."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn: Optional[sqlite3.Connection] = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    # ---------------------------------------------------------------------
    # Schema management
    # ---------------------------------------------------------------------
    def _init_schema(self) -> None:
        """Create tables and indexes if they do not exist."""
        create_sql = """
        CREATE TABLE IF NOT EXISTS tiles (
            map_id INTEGER NOT NULL,
            zoom   INTEGER NOT NULL,
            x      INTEGER NOT NULL,
            y      INTEGER NOT NULL,
            hash   BLOB,
            size   INTEGER,
            etag   TEXT,
            downloaded_at INTEGER,
            last_checked  INTEGER,
            last_changed  INTEGER,
            created_at    INTEGER,
            PRIMARY KEY (map_id, zoom, x, y)
        );
        """
        assert self.conn is not None
        self.conn.execute(create_sql)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_last_checked ON tiles(last_checked);")
        self.conn.commit()

    # ---------------------------------------------------------------------
    # CRUD API
    # ---------------------------------------------------------------------
    def load(self, tile_id: TileID) -> Optional[TileState]:
        """Return a :class:`TileState` for *tile_id* or ``None`` if not present."""
        assert self.conn is not None
        cur = self.conn.execute(
            "SELECT * FROM tiles WHERE map_id=? AND zoom=? AND x=? AND y=?",
            (tile_id.map_id, tile_id.zoom, tile_id.x, tile_id.y),
        )
        row = cur.fetchone()
        if not row:
            return None
        return TileState(
            tile=TileID(map_id=row["map_id"], zoom=row["zoom"], x=row["x"], y=row["y"]),
            hash=row["hash"],
            path=None,  # path resolution is handled by TilePathResolver
            downloaded_at=row["downloaded_at"],
            last_checked=row["last_checked"],
            etag=row["etag"],
            size=row["size"],
        )

    def save(self, state: TileState) -> None:
        """Insert or update a tile record based on :class:`TileState`.

        ``created_at`` is set only on first insert. ``last_changed`` is
        updated when the hash differs from the previous value.
        """
        assert self.conn is not None
        now = int(time.time() * 1000)
        tile_id = state.tile
        existing = self.load(tile_id)
        last_changed = now if (existing is None or existing.hash != state.hash) else existing.last_changed
        sql = """
        INSERT INTO tiles (
            map_id, zoom, x, y,
            hash, size, etag, downloaded_at, last_checked, last_changed, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(map_id, zoom, x, y) DO UPDATE SET
            hash = excluded.hash,
            size = excluded.size,
            etag = excluded.etag,
            downloaded_at = excluded.downloaded_at,
            last_checked = excluded.last_checked,
            last_changed = excluded.last_changed,
            created_at = tiles.created_at;
        """
        self.conn.execute(
            sql,
            (
                tile_id.map_id,
                tile_id.zoom,
                tile_id.x,
                tile_id.y,
                state.hash,
                state.size,
                state.etag,
                state.downloaded_at,
                state.last_checked,
                last_changed,
                now,
            ),
        )
        self.conn.commit()

    def remove(self, tile_id: TileID) -> None:
        """Delete the record for *tile_id* if it exists."""
        assert self.conn is not None
        self.conn.execute(
            "DELETE FROM tiles WHERE map_id=? AND zoom=? AND x=? AND y=?",
            (tile_id.map_id, tile_id.zoom, tile_id.x, tile_id.y),
        )
        self.conn.commit()

    def touch(self, tile_id: TileID, checked_at: int) -> None:
        """Update only the ``last_checked`` timestamp for *tile_id*.

        Use this when a tile has been re-examined but its content has not
        changed. All other columns (``hash``, ``etag``, ``size``, etc.) are
        left untouched.

        Parameters
        ----------
        tile_id:
            Identifier of the tile row to update.
        checked_at:
            Epoch milliseconds to store as ``last_checked``; callers should
            pass ``ctx.timestamp`` so all timestamps are ``TickContext``-based.
        """
        assert self.conn is not None
        self.conn.execute(
            "UPDATE tiles SET last_checked=? WHERE map_id=? AND zoom=? AND x=? AND y=?",
            (checked_at, tile_id.map_id, tile_id.zoom, tile_id.x, tile_id.y),
        )
        self.conn.commit()

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None

    def __enter__(self) -> TileDatabase:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

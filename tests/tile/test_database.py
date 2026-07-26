"""Tests for dynmap_recorder.synchronizers.tile.database (persistence + touch)."""

import pytest
from dynmap_recorder.synchronizers.tile.database import TileDatabase
from dynmap_recorder.synchronizers.tile.models import TileID, TileState


@pytest.fixture
def tile_id():
    return TileID(map_id=1, zoom=2, x=10, y=20)


@pytest.fixture
def state(tile_id):
    return TileState(
        tile=tile_id,
        hash=b"\xde\xad\xbe\xef" * 8,
        path=None,
        downloaded_at=1_000_000,
        last_checked=1_000_000,
        etag='"abc123"',
        size=1024,
        last_modified="Mon, 01 Jan 2026 00:00:00 GMT",
    )


class TestPersistence:
    def test_put_and_get(self, tmp_path, tile_id, state):
        db_file = tmp_path / "tile.db"
        with TileDatabase(db_file) as db:
            db.save(state)
            retrieved = db.load(tile_id)
        assert retrieved is not None
        assert retrieved.hash == state.hash
        assert retrieved.etag == state.etag
        assert retrieved.size == state.size
        assert retrieved.last_modified == state.last_modified

    def test_close_and_reopen(self, tmp_path, tile_id, state):
        """Data persists after closing and reopening the database."""
        db_file = tmp_path / "tile.db"
        with TileDatabase(db_file) as db:
            db.save(state)

        # Re-open a brand-new instance pointing at the same file
        with TileDatabase(db_file) as db2:
            retrieved = db2.load(tile_id)

        assert retrieved is not None
        assert retrieved.hash == state.hash

    def test_get_missing_returns_none(self, tmp_path, tile_id):
        db_file = tmp_path / "tile.db"
        with TileDatabase(db_file) as db:
            assert db.load(tile_id) is None

    def test_remove(self, tmp_path, tile_id, state):
        db_file = tmp_path / "tile.db"
        with TileDatabase(db_file) as db:
            db.save(state)
            db.remove(tile_id)
            assert db.load(tile_id) is None

    def test_put_overwrites(self, tmp_path, tile_id, state):
        new_hash = b"\x11" * 32
        updated = TileState(
            tile=tile_id,
            hash=new_hash,
            path=None,
            downloaded_at=2_000_000,
            last_checked=2_000_000,
        )
        db_file = tmp_path / "tile.db"
        with TileDatabase(db_file) as db:
            db.save(state)
            db.save(updated)
            retrieved = db.load(tile_id)
        assert retrieved.hash == new_hash


class TestTouch:
    def test_touch_updates_last_checked_only(self, tmp_path, tile_id, state):
        db_file = tmp_path / "tile.db"
        with TileDatabase(db_file) as db:
            db.save(state)
            db.touch(tile_id, checked_at=9_999_999)
            retrieved = db.load(tile_id)

        assert retrieved.last_checked == 9_999_999
        # Other columns must remain unchanged
        assert retrieved.hash == state.hash
        assert retrieved.etag == state.etag
        assert retrieved.size == state.size

    def test_touch_nonexistent_tile_noop(self, tmp_path, tile_id):
        """touch() on a missing row should not raise."""
        db_file = tmp_path / "tile.db"
        with TileDatabase(db_file) as db:
            db.touch(tile_id, checked_at=1)  # should not raise


class TestTransaction:
    def test_nested_transaction_commits_all(self, tmp_path, tile_id, state):
        db_file = tmp_path / "tile.db"
        tile_id2 = TileID(map_id=1, zoom=2, x=10, y=21)
        state2 = TileState(tile=tile_id2, hash=b"\x00"*32, path=None, downloaded_at=1000, last_checked=1000)

        with TileDatabase(db_file) as db:
            with db.transaction():
                db.save(state)
                with db.transaction():
                    db.save(state2)

        # Verify both states persisted after outer block exits
        with TileDatabase(db_file) as db2:
            assert db2.load(tile_id) is not None
            assert db2.load(tile_id2) is not None

    def test_transaction_rollback_on_exception(self, tmp_path, tile_id, state):
        db_file = tmp_path / "tile.db"
        with TileDatabase(db_file) as db:
            with pytest.raises(RuntimeError):
                with db.transaction():
                    db.save(state)
                    raise RuntimeError("Simulated DB operation error")

        # Verify state was rolled back and not persisted
        with TileDatabase(db_file) as db2:
            assert db2.load(tile_id) is None

    def test_nested_transaction_rollback_on_inner_exception(self, tmp_path, tile_id, state):
        db_file = tmp_path / "tile.db"
        tile_id2 = TileID(map_id=1, zoom=2, x=10, y=21)
        state2 = TileState(tile=tile_id2, hash=b"\x00"*32, path=None, downloaded_at=1000, last_checked=1000)

        with TileDatabase(db_file) as db:
            with pytest.raises(ValueError):
                with db.transaction():
                    db.save(state)
                    with db.transaction():
                        db.save(state2)
                        raise ValueError("Inner error")

        # Entire transaction should roll back
        with TileDatabase(db_file) as db2:
            assert db2.load(tile_id) is None
            assert db2.load(tile_id2) is None

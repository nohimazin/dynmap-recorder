# Consolidate Tile Synchronizer Components and Simplify Structure

## Goal
Re‑organise the TileSynchronizer package to a leaner layout as requested, reducing the number of source files while preserving functionality. All data structures (`TileID`, `MapInfo`, `HashAlgorithm`, `TileStatus`, `TileState`) will live in a single `models.py`. The synchronizer will consist of the following modules:

```
__init__.py
synchronizer.py   # orchestrates the pipeline
scanner.py        # extracts visible tiles
downloader.py     # HTTP download (single `download` for now)
hasher.py         # hash calculation using `HashAlgorithm`
database.py       # SQLite interaction (tiles table only)
writer.py         # writes PNG files (`write(tile, data)`) 
models.py         # data models and enums
exceptions.py     # custom exception types
```

### User Review Required
> [!IMPORTANT]
> This change will **delete** several existing files (`tile_id.py`, `hash_algorithm.py`, `state.py`, `map_info.py`) and update imports across the package. Ensure no external code depends on those paths.

### Open Questions
> [!CAUTION]
> 1. Do any other parts of the repository (e.g., tests or external scripts) import the now‑removed modules directly? If so, should we provide compatibility shims?
> 2. Should we keep backward‑compatible aliases in `__init__.py` (e.g., `TileID = models.TileID`) to avoid breaking imports?

### Proposed Changes
---
#### Package restructure
- **[DELETE]** `dynmap_recorder/synchronizers/tile/tile_id.py`
- **[DELETE]** `dynmap_recorder/synchronizers/tile/hash_algorithm.py`
- **[DELETE]** `dynmap_recorder/synchronizers/tile/state.py`
- **[DELETE]** `dynmap_recorder/synchronizers/tile/map_info.py`
- **[MODIFY]** `dynmap_recorder/synchronizers/tile/__init__.py` – expose symbols from `models.py` for backward compatibility.
- **[MODIFY]** `dynmap_recorder/synchronizers/tile/database.py` – import `TileID` from `.models` instead of `.tile_id`.
- **[MODIFY]** `dynmap_recorder/synchronizers/tile/hasher.py` – import `HashAlgorithm` and `TileState` from `.models`.
- **[MODIFY]** `dynmap_recorder/synchronizers/tile/downloader.py` – import `TileID` from `.models`.
- **[MODIFY]** `dynmap_recorder/synchronizers/tile/scanner.py` – import `TileID` from `.models`.
- **[MODIFY]** `dynmap_recorder/synchronizers/tile/writer.py` – import `TileState` from `.models`.
- **[NEW]** `dynmap_recorder/synchronizers/tile/models.py` – contains all shared data structures (as already created).

#### Compatibility shim (optional)
If the user prefers, we can add thin wrappers in the deleted modules that re‑export symbols from `models.py`. This would avoid breaking external imports while keeping the new organization.

### Verification Plan
- Run unit‑style import checks (`python -m py_compile`) for the entire package.
- Execute a short end‑to‑end smoke test: create a dummy `TileID`, run `TileHasher` on dummy bytes, store/retrieve via `TileDatabase`, and write a PNG via `TileWriter`.
- Ensure `DynmapPoller` can still import and register `TileSynchronizer` without errors.

---
## Automated Tests
- `python -m pytest` (if test suite exists) after changes.

## Manual Verification
- Load the project in an IDE and confirm no broken imports.
- Run a manual tick with a fabricated `TickContext` to verify the pipeline runs.

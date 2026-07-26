# dynmap-recorder — 実装方針ドキュメント

> 最終更新: 2026-07-20

---

## プロジェクト全体像

Dynmap のタイル画像を定期的に取得・保存する recorder。
`TickContext` を起点に、プレイヤー位置から可視タイルを算出し、
HTTP 取得 → ハッシュ比較 → ファイル書き込み → DB 保存 というパイプラインを実行する。

---

## アーキテクチャ概観

```
TickContext
     │
     ▼
VisibleTileScanner.scan()
     │  List[VisibleTile]
     ▼
TileSynchronizer.on_tick()
     │
     ├─ ThreadPoolExecutor (worker threads)
     │       │  _process_tile() per tile
     │       │    download()  → HTTP + Conditional GET
     │       │    hash()      → BLAKE3 / SHA-256
     │       │    write()     → ファイル書き込み
     │       │    (DB操作なし)
     │       ▼
     │   TileProcessResult
     │
     └─ main thread
             with db.transaction():
               save() / touch()
               COMMIT
```

---

## パッケージ構成

```
dynmap_recorder/synchronizers/tile/
    __init__.py        公開シンボル
    models.py          TileID / MapInfo / TileState / TileProcessResult / VisibleTile
    scanner.py         VisibleTileScanner (ProjectionInfo, better_round)
    downloader.py      TileDownloader (Conditional GET, 304 対応)
    hasher.py          TileHasher (BLAKE3 / SHA-256)
    database.py        TileDatabase (SQLite, transaction())
    synchronizer.py    TileSynchronizer (ThreadPoolExecutor, DI)
    path_resolver.py   TilePathResolver
    writer.py          TileWriter
    settings.py        TileSynchronizerSettings
    factory.py         create_default_synchronizer()
    url_builder.py     TileURLBuilder
    exceptions.py      TileError / TileDownloadError など
```

---

## 完了フェーズ

### ✅ Phase 1–4: DI 化・責務分離リファクタリング

- `TileSynchronizer` を純粋なオーケストレータ化
- 依存をコンストラクタ DI に統一
- `TileSynchronizerSettings` と `factory.py` の役割分離
- helper チェーン: `on_tick → _process_tile → _download → _should_update → _write_tile → _build_state`

### ✅ Phase 5-A: Conditional GET / 304 Not Modified 対応

- `TileState.last_modified` を DB スキーマに追加
- `TileDownloader.download()` に `etag` / `last_modified` 引数追加
- `If-None-Match` / `If-Modified-Since` ヘッダを送信
- `DownloadResult.status == 304` を正常系として処理
- DB の `touch()` メソッドで `last_checked` のみ更新

### ✅ Phase 5-B: VisibleTileScanner リファクタリング

- `ProjectionInfo` dataclass (`worldtomap`, `tile_size`, `max_zoom`)
- `_projection_cache: Dict[int, ProjectionInfo]` でキャッシュ
- private helper: `_filter_players`, `_project_player`, `_center_tile`
- `_scan_grid()` でタイルを生成（重複除去 + 優先度ソート）
- `better_round(num, base, tile_size=128)` で `tile_size` を設定可能に

### ✅ Phase 6: transaction() / TileProcessResult / ThreadPoolExecutor

**Phase 6-1: `db.transaction()` の実装**
- `_transaction_depth: int` でネスト対応
- `depth==0` のときだけ `COMMIT` / `ROLLBACK`
- `save()` / `touch()` / `remove()` の個別 commit をガード

**Phase 6-2 / 6-3: `_process_tile()` の戻り値変更**
- `TileProcessResult` dataclass を追加 (`models.py`)
- `_process_tile()` が DB を直接更新しなくなった
- 戻り値: `state` (save 用) / `touched` / `downloaded` / `failed` / `checked_at`

**Phase 6-4: `on_tick()` の並列化と DB 集約**
- `ThreadPoolExecutor(max_workers)` で並列ダウンロード
- 全 worker 完了後に `with db.transaction():` で一括 COMMIT
- `max_workers: int = 4` を `TileSynchronizerSettings` / `factory.py` に追加

---

## 現在の既知の技術的負債 / 要対応事項

### 🔧 scanner.py — dead code

`better_round` 関数に unreachable な旧実装が残っている (L31–32)。

```python
# 現状 (L24–32)
def better_round(num: float, base: int, tile_size: int = 128) -> int:
    scaled = float(num) / tile_size
    return int(base * math.ceil(scaled))
    """Round a number up to the nearest multiple of base."""  # ← dead code
    return int(base * math.ceil(float(num) / base))          # ← dead code
```

→ L31–32 を削除するだけでよい。

---

## 次フェーズの候補

### Phase 7: Retry / エラーハンドリング強化

`TileProcessResult.failed == True` のタイルを次の tick で再試行する仕組み。

```python
# 設計案
@dataclass
class RetryQueue:
    tiles: List[VisibleTile]
    attempts: Dict[TileID, int]
    max_attempts: int = 3
```

- `on_tick()` の冒頭で前回失敗分を先頭に追加
- `attempts[tile_id] >= max_attempts` になったらスキップ＆ログ

### Phase 8: Metrics / Progress 表示

`TileProcessResult` のフィールドを集計してログ出力。

```
Tick #42: 128 tiles scanned
  downloaded: 23  (new/changed)
  touched:    98  (304 / unchanged)
  failed:      7  (retry pending)
  elapsed:   1.23s
```

`TileSynchronizer` に `_summarize_results(results)` メソッドを追加するだけで実装可能。

### Phase 9: Rate Limit / バックプレッシャー

- `max_workers` を動的に調整（HTTP 429 が増えたら下げる）
- `Semaphore` または `asyncio.Semaphore` を使ったリクエスト数制限

---

## テスト状況

```
tests/tile/
    test_database.py       7件  ✅ (transaction ネスト未テスト → Phase 6 残タスク)
    test_downloader.py     9件  ✅
    test_hasher.py         6件  ✅ (2 skipped: blake3 native)
    test_imports.py        1件  ✅
    test_path_resolver.py  3件  ✅
    test_scanner.py        4件  ✅
    test_synchronizer.py   6件  ✅
    test_url_builder.py    3件  ✅
    test_writer.py         4件  ✅

計: 44 passed, 2 skipped
```

**未カバー領域:**
- `db.transaction()` のネスト動作・rollback シナリオ
- `on_tick()` の `transaction()` 統合 (end-to-end)
- `scanner.py` の projection 行列を使った座標変換の精度検証

---

## 設計上の方針 (決定済み)

| 項目 | 決定内容 |
|---|---|
| Projection の抽象化 | 現時点では不要 (YAGNI)。BlueMap 等が必要になった時点で `Projection Protocol` を追加する |
| `zoom_levels` の `ProjectionInfo` 含有 | 不要。`max_zoom` は `MapInfo` で保持 |
| Map毎の `scan_radius` | 現時点では不要 |
| SQLite 並列書き込み | Worker thread では書き込みせず、main thread の `transaction()` に集約 |
| `max_workers` デフォルト | `4`。`settings.py` で変更可能 |

# dynmap-recorder — 実装方針ドキュメント

> 最終更新: 2026-07-26

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
    scanner.py         VisibleTileScanner (Dynmap設定キー、ProjectionInfo, better_round)
    downloader.py      TileDownloader (Conditional GET, 304 対応)
    hasher.py          TileHasher (BLAKE3 / SHA-256)
    database.py        TileDatabase (SQLite, transaction())
    synchronizer.py    TileSynchronizer (ThreadPoolExecutor, DI)
    path_resolver.py   TilePathResolver
    writer.py          TileWriter
    settings.py        TileSynchronizerSettings
    factory.py         create_default_synchronizer()
    url_builder.py     TileURLBuilder (Dynmap標準URL形式)
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

### 🔧 残りの技術的負債

実サーバーでのタイル取得は確認済み。残りはHTTP異常系を含むポーラー全体のE2E試験と、より広い座標境界の検証。

---

## 次フェーズの候補

### ✅ Phase 7: Retry / エラーハンドリング強化


実装済み:
- retry / scanner の重複は `TileID` で除去し、retry 側を優先
- `TileDownloadError.retryable == True` の失敗だけを再試行対象にする

追加実装:
- `DynmapPoller` から `TileSynchronizer` をサーバー設定取得後に遅延初期化
- CLI / `config.json` から `tile_recorder`、スキャン半径、ワーカー数、ハッシュ方式を設定可能化
- ポーリング処理を `TickContext` / `on_tick()` に統一し、タイル同期へプレイヤー状態を供給
- ポーラー終了時にタイルDB接続をクローズ
- ポーラー統合テストを追加

### Phase 8: Metrics / Progress 表示

✅ `TileProcessResult` のフィールドを集計してログ出力。

- `TickMetrics` を `TileSynchronizer.on_tick()` の戻り値として追加
- scanned / retry / downloaded / updated / touched / failed / retried / dropped / elapsed_ms を集計
- `--verbose` 時にINFOログを表示
- Retry Queue の上限を1000件に設定し、超過分を `dropped` として記録
- 実SQLite・実ファイルを使う同期パイプラインテストを追加

### ✅ Phase 8-B: 実Dynmapサーバー対応・検証

- Dynmap標準URL形式（`tiles/<world>/<prefix>/<chunk>/<zoom>_<x>_<y>.<format>`）に対応
- `image-format` / `tilescale` / `mapzoomout` のネイティブ設定キーに対応
- タイル保存先の拡張子をマップの画像形式に合わせて決定
- 実サーバー `kuromaru-web-proxy.fly.dev` でプレイヤー座標を取得
- 実サーバーから140枚のタイルを取得し、全件更新・保存を確認
- SQLiteに140件のタイル状態を保存

```
Tick #42: 128 tiles scanned
  downloaded: 23  (new/changed)
  touched:    98  (304 / unchanged)
  failed:      7  (retry pending)
  elapsed:   1.23s
```

### Phase 9: Rate Limit / バックプレッシャー

- `max_workers` を動的に調整（HTTP 429 が増えたら下げる）
- `Semaphore` または `asyncio.Semaphore` を使ったリクエスト数制限

---

## テスト状況

```
全テスト: 66 passed, 2 skipped
```

**未カバー領域:**
- `scanner.py` の projection 行列を使った座標変換の精度検証
- ポーラー全体のHTTP異常系E2E（304 / Timeout / 404 / Retry→Success）
- Poller経由でのタイルDownloader異常系（304 / 404 / Retry→Success）

実サーバー検証で確認済み:
- Dynmap APIからプレイヤー座標を取得
- 実Dynmap URL形式で140枚のタイルを取得・保存
- 実SQLiteに140行を保存
- `image-format`、`tilescale`、`mapzoomout`を含むDynmap設定を読み込み

残りの検証候補:
- ポーラー全体のHTTP異常系E2E（304 / Timeout / 404 / Retry→Success）
- Flat / Surfaceの境界座標・遠方座標での位置一致確認

---

## 設計上の方針 (決定済み)

| 項目 | 決定内容 |
|---|---|
| Projection の抽象化 | 現時点では不要 (YAGNI)。BlueMap 等が必要になった時点で `Projection Protocol` を追加する |
| `zoom_levels` の `ProjectionInfo` 含有 | 不要。`max_zoom` は `MapInfo` で保持 |
| Map毎の `scan_radius` | 現時点では不要 |
| SQLite 並列書き込み | Worker thread では書き込みせず、main thread の `transaction()` に集約 |
| `max_workers` デフォルト | `4`。`settings.py` で変更可能 |

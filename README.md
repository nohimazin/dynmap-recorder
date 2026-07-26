# dynmap-recorder

Dynmap / LiveAtlas からワールド更新情報、プレイヤー状態、イベント、タイル画像を取得・保存する Python 製レコーダーです。

## 概要

定期的に Dynmap API をポーリングし、次のデータを保存します。

- プレイヤーの位置・体力・装備・オンライン状態
- チャット、Webチャット、参加・退出イベント
- プレイヤー周辺の可視タイル画像
- ポーリング状態とメタデータ

タイルレコーダーは、プレイヤー位置から可視タイルを算出し、HTTP取得・ハッシュ比較・ファイル保存・SQLite更新を行います。ETag / Last-Modified による Conditional GET、304対応、並列ダウンロード、失敗タイルの次tick再試行にも対応しています。

## 必要環境

- Python 3.10 以降
- Dynmap または LiveAtlas の公開API
- タイルをBLAKE3でハッシュする場合は `blake3` パッケージ

## セットアップ

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip pytest
```

BLAKE3を使用する場合は、環境に応じて追加インストールします。

```powershell
python -m pip install blake3
```

## 基本的な使い方

サーバーURLを指定して起動します。

```powershell
python dynmap_collector.py --base https://example.com/dynmap
```

設定ファイルを使う場合は、[config.json](config.json) に `base` などを設定します。

```json
{
  "base": "https://example.com/dynmap",
  "world": "world",
  "output_dir": "outputs",
  "event_recorder": true,
  "player_recorder": true,
  "tile_recorder": false
}
```

CLIオプションは設定ファイルより優先されます。

## 主なCLIオプション

| オプション | 説明 |
|---|---|
| `--base URL` | Dynmap / LiveAtlas のベースURL |
| `--world NAME` | 対象ワールド名 |
| `--interval SEC` | ポーリング間隔（秒） |
| `--duration SEC` | 実行時間。`0` または未指定で継続実行 |
| `--output-dir DIR` | 出力先ルート |
| `--snapshot` | 初回プレイヤー一覧を保存 |
| `--infer-player-events` | プレイヤー一覧の差分から参加・退出を推定 |
| `--verbose` | 詳細ログとタイル進捗ログを表示 |
| `--no-event-recorder` | イベント記録を無効化 |
| `--no-player-recorder` | プレイヤー記録を無効化 |
| `--tile-recorder` | タイル記録を有効化 |
| `--tile-scan-radius N` | プレイヤー周辺のタイル走査半径 |
| `--tile-max-workers N` | タイル取得の並列ワーカー数 |
| `--tile-hash-algorithm` | `blake3` または `sha256` |

タイル記録を有効にする例です。

```powershell
python dynmap_collector.py `
  --base https://example.com/dynmap `
  --world world `
  --tile-recorder `
  --tile-scan-radius 2 `
  --verbose
```

## 出力構成

既定の出力先は `outputs/` です。

```text
outputs/
├─ metadata/
│  ├─ players.json
│  ├─ worlds.json
│  └─ schema.json
├─ recorder/
│  └─ players/
│     └─ YYYY-MM-DD.jsonl
├─ dynmap_events.jsonl
├─ dynmap_events.csv
├─ state/
│  └─ dynmap_state.json
└─ tiles/
   ├─ tiles.db
   └─ <world>/<map>/<tileset>/z<zoom>/<x>/<y>.<format>
```

`outputs/` は実行時に生成されるデータであり、通常はGit管理対象に含めません。

## タイル同期の処理フロー

```text
DynmapPoller
    ↓
TickContext
    ↓
VisibleTileScanner
    ↓
TileSynchronizer
    ├─ 並列HTTPダウンロード
    ├─ ETag / Last-ModifiedによるConditional GET
    ├─ BLAKE3 / SHA-256ハッシュ比較
    ├─ タイルファイル書き込み
    └─ SQLite transactionで状態更新
```

タイル取得に失敗した場合は、再試行可能なエラーだけが次のtickへ再投入されます。再試行回数はタイルごとに制限され、Retry Queueの上限は1,000件です。

各tickでは、次のようなメトリクスを取得・ログ出力できます。

```text
tiles=84 retry=1 downloaded=16 updated=16 touched=61 failed=2 retried=1 dropped=0 (54.3ms)
```

## テスト

```powershell
python -m pytest -q
```

現在のテスト結果は `65 passed, 2 skipped` です。単体テスト、Scanner / Downloader / SQLiteのコンポーネントテスト、TileSynchronizer統合テスト、Poller統合・異常系テスト、実SQLite・実ファイルを使ったE2E相当テストを含みます。

## 既知の制約と今後の検証

- 実Dynmapサーバーでプレイヤー座標からタイル画像保存まで確認済みです。
- Flat / Surfaceマップ、`image-format`・`tilescale`・`mapzoomout`設定に対応しています。
- 実HTTP経路を使ったPoller全体の304 / 404 / Retry→Success検証は今後の追加候補です。
- `.venv` に依存パッケージをインストールしていない場合、システム側Pythonでテストを実行してください。

## 設計方針

- タイル処理は依存性注入（DI）で構成する
- Worker threadではSQLiteを書き込まず、呼び出し側のtransactionに集約する
- HTTPの一時的障害だけを再試行する
- Dynmap固有の座標変換を優先し、他マップサービス向けの抽象化は必要になるまで追加しない

## ライセンス

ライセンスについては [LICENSE](LICENSE) を参照してください。

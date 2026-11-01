# Phase 8 拡張（詳細メトリクス） 実装計画

## 概要

既存の `TickMetrics` と役割が重複しないよう、タイル単位の詳細な計測を行う `TileMetrics` と `MetricsAggregator` を導入する。
Downloader 内部の HTTP リトライと、Retry Queue による次 tick への再投入回数を別々に管理・記録し、Worker Thread から共有 Aggregator や DB への直接アクセスを避けるスレッドセーフな集約アーキテクチャを確立する。

---

## 役割分担

| クラス | 責務 |
|---|---|
| `TileProcessResult` | DB保存・touch・失敗の判定 |
| `TileMetrics` | 1タイルの処理時間、転送量、リトライ数など |
| `MetricsAggregator` | タイル単位のメトリクス集約 |
| `TickMetrics` | 1 tick 全体の集計結果（既存クラスを再利用・拡張） |

---

## 変更ファイル

### 1. [downloader.py](file:///C:/Users/himazin/AntigravityProject/dynmap-recorder/dynmap_recorder/synchronizers/tile/downloader.py)
- `DownloadResult` に `retry_count: int = 0` を追加。
- `download()` 成功時および 304 時に `retry_count = attempt - 1` を設定。

### 2. [metrics.py](file:///C:/Users/himazin/AntigravityProject/dynmap-recorder/dynmap_recorder/synchronizers/tile/metrics.py)
- `TileMetrics` dataclass を定義：
  - `tile_id: TileID`
  - `elapsed_ms: float = 0.0`
  - `retries: int = 0` (HTTP retry count)
  - `bytes_downloaded: int = 0`
  - `downloaded: bool = False`
  - `updated: bool = False`
  - `not_modified: bool = False` (HTTP 304)
  - `unchanged: bool = False` (HTTP 200 hash match)
  - `failed: bool = False`
- `TickMetrics` の既存定義を復元・拡張（`bytes_downloaded`, `http_retries`, `not_modified`, `unchanged` をサポート）。
- `MetricsAggregator` クラスを実装：
  - `record(metrics: TileMetrics) -> None`
  - `summary(...) -> TickMetrics`
  - `reset() -> None`
  - `format_log(metrics: TickMetrics) -> str`

### 3. [synchronizer.py](file:///C:/Users/himazin/AntigravityProject/dynmap-recorder/dynmap_recorder/synchronizers/tile/synchronizer.py)
- `_process_tile()` で `time.perf_counter()` を用いて処理時間を計測し、`(TileProcessResult, TileMetrics)` のタプルを返却。
- `on_tick()` で Future 回収後に Main Thread で `aggregator.record(tile_metric)`。
- DB トランザクション完了後に Retry Queue を更新し、`TickMetrics` を生成してログ出力＆返却。

### 4. [tests/tile/test_metrics.py](file:///C:/Users/himazin/AntigravityProject/dynmap-recorder/tests/tile/test_metrics.py) & [tests/tile/test_synchronizer.py](file:///C:/Users/himazin/AntigravityProject/dynmap-recorder/tests/tile/test_synchronizer.py)
- `TileMetrics`, `MetricsAggregator`, `TickMetrics` の単体テスト。
- `test_synchronizer.py` の `_process_tile` テストをタプル返却対応に更新。

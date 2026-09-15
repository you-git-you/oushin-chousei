# PlanetScale への移行手順（割当ストア）

## 前提

- ローカル正本: `db/schedule.sqlite`
- 論理スキーマ: [`scripts/schema_schedule.sql`](../scripts/schema_schedule.sql)（SQLite）
- MySQL DDL: [`schema_schedule.mysql.sql`](schema_schedule.mysql.sql)

## データモデル

| テーブル | 役割 |
|----------|------|
| `schedule_period` | 調整期間（例: `2026-08`） |
| `schedule_assignment` | 日 × 医師 × 順番 × 患者 chart_id |
| `schedule_revision` | 変更履歴（routes JSON スナップショット） |

アプリは `ScheduleRepository` 経由でのみアクセスする。実装は [`scripts/schedule/sqlite_store.py`](../scripts/schedule/sqlite_store.py)。

## 移行ステップ

1. PlanetScale で DB を作成し、`schema_schedule.mysql.sql` を適用する。
2. `scripts/schedule/mysql_store.py`（未実装）を追加し、`ScheduleRepository` を実装する。
   - 接続: 環境変数 `DATABASE_URL`（`mysql://...`）
3. ファクトリ `get_schedule_repository()` で `DATABASE_URL` があれば MySQL、なければ SQLite を選ぶ。
4. 初回データ移行:
   ```bash
   python3 scripts/export_schedule_json.py
   # JSON を PlanetScale へ import するか、replace_routes をリモート向けに1回実行
   ```
5. Workers / API では `get_routes` / `replace_routes` と同じ JSON 形状を REST で公開する。

## SQLite と MySQL の差分

- 主キーは UUID 文字列（`CHAR(36)`）で共通。
- 日時は ISO8601 文字列（タイムゾーン付き UTC）で共通。
- SQLite の `PRAGMA foreign_keys` に依存する削除順序は、MySQL 側でもトランザクション内で `DELETE` → `INSERT` とする。

## 患者マスタ

`oushin.sqlite`（患者・イベント）は別系統。PlanetScale に載せる場合も `schedule_*` と分離し、`patient_chart_id` は論理参照のみ（FK は任意）。

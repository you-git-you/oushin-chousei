# データ辞書（往診調整DB）

正本: `db/oushin.sqlite`  
取込元: `raw/*.csv`

## 保険区分 `insurance_type`

| 値 | 意味 | 期限ルール |
|---|---|---|
| `kaigo` | 介護保険 | 最終実施日の2ヶ月後月末 |
| `iryo` | 医療保険 | 最終実施日の30日後 |
| `jihi` | 自費 | 介護と同じ（2ヶ月後月末） |
| `unknown` | 台帳未突合など | 介護と同じ扱いで計算し、要確認とする |

台帳の「介護度」列から分離する。

- `医療` → `insurance_type=iryo`, `care_level=NULL`
- `自費` → `insurance_type=jihi`, `care_level=NULL`
- `要介護*` / `要支援*` など → `insurance_type=kaigo`, `care_level=元値`
- 空 → `insurance_type=unknown`

## 患者状態 `patients.status`

| 値 | 意味 |
|---|---|
| `active` | 継続中（台帳の状態が空） |
| `paused` | 休止中（休止管理に存在、または同期後） |
| `ended` | 終了 |
| `scheduled` | 予定（台帳の状態が「予定」） |

## イベント種別 `events.event_type`

| 値 | 意味 | 主な取込元 |
|---|---|---|
| `home_visit` | 往診 | 往診履歴 / 往診予約（往診） |
| `clinic_visit` | クリニック受診・通院 | クリニック受診 / 往診予約（通院） |
| `phone` | 電話 | 往診予約（電話） |

## イベント状態 `events.status`

| 値 | 意味 | 期限計算 |
|---|---|---|
| `completed` | 実施完了 | 使う |
| `needs_review` | 要確認（実施済みの可能性が高い） | 使う |
| `scheduled` | 予定（未実施） | 使わない |
| `cancelled` | キャンセル | 使わない |

## イベント取込元 `events.source`

| 値 | 意味 |
|---|---|
| `oushin_rireki` | 往診履歴 CSV |
| `yoyaku` | 往診予約 CSV |
| `clinic` | クリニック受診 CSV |
| `confirmed_record` | 手動確定（`records/data/*.json` → `import_visit_records.py --sync-oushin`） |

## 日付の扱い

- 保存形式は ISO 日付 `YYYY-MM-DD`（時刻が分かる場合は `performed_at` に日付部分のみ、詳細は `note` または別カラム検討）
- 未来日の `scheduled` は最終実施日に含めない
- 「最終実施日」= `status IN ('completed','needs_review')` かつ `performed_at <= 基準日` の最大値

## ID体系

| フィールド | 例 | 説明 |
|---|---|---|
| `patient_id` | `b075` | 内部PK。台帳 `b75` をゼロ埋め正規化 |
| `chart_id` | `b75` | 台帳元ID |
| `visit_code` | `000075` | 往診履歴の患者ID |
| `notion_page_id` | UUID | Notion ページID（取得できた場合） |

突合優先順位: `visit_code` / `chart_id` → `notion_page_id` → 正規化氏名（補助）

## 割当スケジュール `db/schedule.sqlite`

患者マスタとは別ファイル。詳細 DDL は `scripts/schema_schedule.sql`。

| テーブル | 説明 |
|---|---|
| `schedule_period` | 期間キー（例: `2026-08`） |
| `schedule_assignment` | `day_key` + `doctor` + `sort_index` + `patient_chart_id` |
| `schedule_revision` | 変更時の `routes` JSON スナップショット |

`patient_chart_id` は生成器の `chart_id`（例: `b494`）と一致。PlanetScale 用 DDL は `docs/schema_schedule.mysql.sql`。

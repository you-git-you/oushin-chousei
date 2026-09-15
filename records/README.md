# 往診実施記録（手動確定分）

## 方針

| 層 | 役割 |
|---|---|
| **Markdown（`records/*.md`）** | 人が読む正本。ルート表・未実施・リスケの説明 |
| **JSON（`records/data/*.json`）** | 取込用の構造化データ（MDと内容を揃える） |
| **SQLite（`db/visit_records.sqlite`）** | 確定実施の検索・期限再計算・一覧出力用 |

Notion 由来の一括履歴は引き続き `db/oushin.sqlite`（`raw/*.csv` 取込）が正本です。  
**スタッフが確定した直近の往診**は、予定CSVや往診履歴シートよりこちらの記録を優先します。

## 更新手順

1. 実施後、`records/20XX-XX_往診実施確定.md` にルートを追記（または新規ファイル）
2. 同内容を `records/data/confirmed_visits.json` に反映
3. DB へ取込:

```bash
python3 scripts/init_visit_records_db.py    # 初回のみ
python3 scripts/import_visit_records.py
```

4. （任意）期限計算用にメインDBへ同期:

```bash
python3 scripts/import_visit_records.py --sync-oushin
```

5. 一覧の再出力:

```bash
python3 scripts/export_visit_records.py
python3 scripts/export_september_targets.py   # 9月往診対象一覧
```

## ファイル一覧

| ファイル | 内容 |
|---|---|
| [直近往診実施一覧.md](./直近往診実施一覧.md) | 確定実施のサマリ（スクリプトで更新可） |
| [2026-07_往診実施確定.md](./2026-07_往診実施確定.md) | 2026年7月の確定ルート詳細 |
| [2026-07_未実施とリスケ.md](./2026-07_未実施とリスケ.md) | 7/27リスケ・未実施 |
| [履歴データの整理.md](./履歴データの整理.md) | 全体のデータの見方 |
| [data/confirmed_visits.json](./data/confirmed_visits.json) | 取込用JSON |
| [data/pause_resume_status.json](./data/pause_resume_status.json) | 休止・再開スナップショット |
| [休止再開_現状一覧.md](./休止再開_現状一覧.md) | 休止状態サマリ（スクリプト生成） |
| [9月往診対象一覧_2026.md](./9月往診対象一覧_2026.md) | 9月往診が必要な方（スプレッドシート用TSV付き） |
| [data/august_2026_medical.json](./data/august_2026_medical.json) | 8月往診リストの医療6名 |
| [data/clinic_visits_as_performed.json](./data/clinic_visits_as_performed.json) | スタッフチャット分の通院（「予定」も実施扱い） |
| [クリニック受診_スタッフチャット実施扱い.md](./クリニック受診_スタッフチャット実施扱い.md) | 上記の人向け一覧 |
| [2026-09_医師ドライバー希望.md](./2026-09_医師ドライバー希望.md) | 9月往診の医師・ドライバー希望（割当前） |
| [data/september_2026_staff_availability.json](./data/september_2026_staff_availability.json) | 上記のJSON（スクリプト用） |

### 休止・再開

```bash
python3 scripts/import_pause_resume.py --sync-oushin
```

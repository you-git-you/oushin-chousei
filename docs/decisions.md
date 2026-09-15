# 設計判断（往診DB正規化）

実装開始時点で確定した方針です。

| 項目 | 選択 | 内容 |
|---|---|---|
| 正本の置き場 | A | ローカル SQLite（`db/oushin.sqlite`）を正本。Notion CSV は取込元 |
| 8月割当・順番 | B | `db/schedule.sqlite`（`schedule_*` テーブル）。将来 PlanetScale へ同一スキーマで移行 |
| 初期ゴール | A | Phase 0〜3（ID統合＋イベント正本＋期限一覧自動出力） |
| 医療の期限 | A | 最終実施日のちょうど **30日後** |
| 未突合患者 | A | 期限一覧に残し「要確認」として目視修正する |
| 直近の確定実施 | A | 人間可読は `records/*.md`、取込は `records/data/*.json` → `db/visit_records.sqlite`。任意で `oushin.sqlite` に `source=confirmed_record` で同期 |

介護・自費の期限は、最終実施日の **2ヶ月後の月末** です。

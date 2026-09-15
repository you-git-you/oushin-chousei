# 月次往診リスト — 運用チェックリスト

毎月のリスト作成・更新時にこのチェックリストを使う。完了したら `[x]` にし、レビューは `tasks/todo.md` に追記する。

## 1. データ準備

- [ ] 最新の希望CSVをプロジェクトルートに配置（`🚙🚕🚗往診周り順… - <月>月往診日・希望.csv`）
- [ ] 最新の編集用台帳CSVを配置（`★台帳（訪問）★ 編集用…`）
- [ ] 休止・再開・クリニック受診の更新を `records/` に反映
- [ ] `python3 scripts/import_from_csv.py`
- [ ] `python3 scripts/import_visit_records.py`（確定実施がある場合）
- [ ] `python3 scripts/import_pause_resume.py --sync-oushin`（休止更新がある場合）

## 2. 医師・ドライバー枠の確認

- [ ] `往診ルール` と最新希望CSVで花輪の月曜日を確認
- [ ] 片山の実施日（月ごとに異なる）を確認
- [ ] 鳥越の土曜日を確認
- [ ] ドライバー希望を `records/20XX-XX_医師ドライバー希望.md` に記録（任意）

## 3. スクリプト準備

- [ ] 前月の `generate_*_schedule.py` を複製し当月用にリネーム
- [ ] 前月の `build_*_schedule_html.py` を複製し当月用にリネーム
- [ ] 希望CSVパス・医師枠・片山実施日・除外IDをスクリプト内で更新

## 4. 生成・調整

- [ ] `python3 scripts/generate_<月>_schedule.py`
- [ ] `python3 scripts/build_<月>_schedule_html.py`
- [ ] `bash scripts/open_schedule_in_chrome.sh` でブラウザ確認
- [ ] 医師NG（三原・木村・渡部）の衝突がないこと
- [ ] TIME_NG_WARN がないこと（ETA で時間帯NGを検証）
- [ ] 同建物・近接エリアの連続訪問を確認
- [ ] 手動並び替え後、overrides JSON を保存して再生成

## 5. レビュー・記録

- [ ] `tasks/todo.md` にレビュー（日付・変更内容・ETA確認結果）
- [ ] 新しい教訓があれば `tasks/lessons.md` に追記
- [ ] 問題・寄せきれない制約をリストの報告セクションに記載

## 参考コマンド

```bash
# 期限一覧の出力
python3 scripts/export_deadlines.py --as-of YYYY-MM-DD --cutoff YYYY-MM-DD

# 往診対象一覧（月次）
python3 scripts/export_september_targets.py   # 当月用スクリプトに置き換え

# CLI で overrides 適用（API 未使用時）
python3 scripts/apply_schedule_overrides.py ~/Downloads/schedule_overrides.json
```

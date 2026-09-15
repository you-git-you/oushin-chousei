# 往診調整データベース

Notion 由来 CSV（0〜5）を正規化し、SQLite を正本として往診期限を管理します。

## 方針

詳細は [docs/decisions.md](docs/decisions.md) / [docs/data-dictionary.md](docs/data-dictionary.md)。

- 正本: `db/oushin.sqlite`
- 取込元: `raw/*.csv`
- 医療期限: 最終実施日の **30日後**
- 介護・自費: 最終実施日の **2ヶ月後月末**

## 使い方

```bash
# 1. CSV を raw/ に置く（初回はコピー済み）

# 2. 取込（DBを再構築）
python3 scripts/import_from_csv.py

# 3. 期限一覧の出力
python3 scripts/export_deadlines.py --as-of 2026-07-16 --cutoff 2026-08-31
```

出力先:

- `exports/往診期限一覧_YYYYMMDDまで.md`
- `exports/往診期限一覧_YYYYMMDDまで.csv`
- `exports/unmatched_patients.md`

## 直近の確定往診（手動記録）

スタッフ確認済みの実施ルートは CSV より `records/` を優先します。

```bash
python3 scripts/init_visit_records_db.py          # 初回のみ
python3 scripts/import_visit_records.py           # JSON → visit_records.sqlite
python3 scripts/import_visit_records.py --sync-oushin   # 任意: 期限DBへ同期
python3 scripts/export_visit_records.py           # 直近一覧 MD を再生成
```

詳細: [records/README.md](records/README.md)

## 8月往診リスト（並び替え・別日移動）

```bash
# 推奨: ローカル API + ブラウザ（保存が1クリック）
bash scripts/open_schedule_in_chrome.sh
# または
python3 scripts/schedule_server.py
# → http://127.0.0.1:8765/
```

- **保存する** … `schedule.sqlite` に書き込み → MD/HTML 再生成（API 未起動時のみ JSON ダウンロード）
- 行左の `⋮⋮` … 同じ医師内の並び替え
- 「日」ボタン … 移動先リストで挿入位置を選択

### 割当DB（初回・別マシン）

```bash
python3 scripts/init_schedule_db.py
python3 scripts/seed_schedule_from_md.py
```

### JSON / CLI（API を使わない場合）

```bash
python3 scripts/apply_schedule_overrides.py ~/Downloads/schedule_overrides.json
```

- **正本（割当）**: `db/schedule.sqlite`
- PlanetScale 移行: [docs/planetscale-migration.md](docs/planetscale-migration.md)
- 制約データ: `exports/patient_constraints.json`（HTMLに埋め込み）

## ディレクトリ

| パス | 内容 |
|---|---|
| `raw/` | 元CSV・往診ルール |
| `db/` | SQLite 正本（`oushin.sqlite` 患者、`schedule.sqlite` 割当） |
| `scripts/` | 取込・出力 |
| `exports/` | 期限一覧など |
| `records/` | 手動確定の往診実施記録（MD正本・JSON取込） |
| `docs/` | データ辞書・判断記録 |

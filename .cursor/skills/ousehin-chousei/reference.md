# 往診調整 詳細リファレンス

## 主要ファイル

| 用途 | パス例 |
|------|--------|
| 生成スクリプト | `scripts/generate_august_schedule.py` |
| 希望日 | `*8月往診日希望*.csv` |
| 台帳 | `★台帳（訪問）★ 編集用*.csv` |
| 出力 | `exports/8月往診リスト_2026.md` |
| 医師ルール | `往診ルール` |
| クリニック通院（実施扱い） | `records/data/clinic_visits_as_performed.json` |
| 9月医師・ドライバー希望 | `records/data/september_2026_staff_availability.json` |

## クリニック受診の記録

- スタッフチャットの「クリニック受診予定」は **実施済み** として `clinic_visits_as_performed.json` に追記する（Notionが「予定」のままでも同様）。
- `scripts/clinic_visits.py` が通院の最終日計算にこのJSONをマージする。
- 人向け一覧: `records/クリニック受診_スタッフチャット実施扱い.md`

## 医師NG（固定）

SKILL.md の原文どおり:

- 三原千砂子（b484）… 片山医師NG → 片山枠に入れない。8月実績は 8/22 鳥越
- 木村一久（b357）… 鳥越医師NG → 土曜鳥越に入れない。8月実績は 8/24 花輪AM（11時前）
- 渡部光子（b138）… 鳥越医師のみOK → 月曜花輪・片山に入れない。土曜14時以降。9月は 9/5 鳥越

`classify_doctor_pref`: コメントに「片山」かつ「NG」→ `torikoe`、「鳥越」かつ「NG」→ `hanawa`。渡部はピンで鳥越固定。

## 固定しやすい特例

- `DEPARTURE_TRAVEL_MIN_BY_ID`: b216=40, b288=40
- `BUILDING_CLUSTERS`: S大泉北 / FH大泉 / L谷原 / 平峯 / 寺野 / 齊藤荘 / S井荻 など
- 同日不可の例: CW下石（後藤月曜のみ／萱槇土曜のみ）、S井荻（松村月曜／上東・鳥山土曜）

## ルート先頭の例外

通常は三鷹を末尾にしがちだが、指定があれば先頭:

- b288 → 花輪の一番最初
- b216 → 鳥越の一番最初

`time_window_priority` の `-1` と `apply_time_window_order` を参照。

## 連続訪問の寄せ（詳細）

### 判定基準

| レベル | 条件 | 対応 |
|--------|------|------|
| A | 住所の建物名・施設名が同一 | 必ず連続（`pair_with` または `BUILDING_CLUSTERS`） |
| B | `area` が同一（石町・FH大泉など） | 同日ルート内で連続を優先 |
| C | 隣接エリア（移動12分以内目安） | 折り返しが発生していれば並び替え検討 |

### コード上のフック

- `BUILDING_CLUSTERS`（`generate_august_schedule.py`）: 同日寄せのクラスタ定義
- `build_visit_units` / `apply_time_window_order`: 同建物を一塊にソート
- `exports/schedule_overrides.json` → `routes`: **手動並び替えの正**（HTML DnD 保存先）
- `AREA_CLUSTER_ORDER`: エリア順のデフォルト（連続寄せの参考）

### 並び替え時の検証

```bash
python3 scripts/apply_schedule_overrides.py
```

再生成後、該当日の **動線行** と **時間NG列** を確認。衝突時は NG・期限を優先し連続は諦める。

## 再生成チェックリスト

- [ ] 花輪 ≤5（日） / 片山 ≤11 / 鳥越 定員内（**16:30帰宅は目安・厳密判定しない**）
- [ ] 医療の1回目が期限前、2回目が同月延長どおり
- [ ] 未割当なし
- [ ] 同建物クラスタが意図どおり同日
- [ ] **同建物・同エリアがルート内で連続**（折り返しなし）
- [ ] 水上・鴇田の先頭ETAが出発+40分
- [ ] 医師NG: 三原≠片山、木村≠鳥越、渡部＝鳥越のみ

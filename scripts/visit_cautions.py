"""往診時の注意点（日別・印刷対象）。画像は exports/ からの相対パス。"""

from __future__ import annotations

DAY_VISIT_CAUTIONS: dict[str, list[dict[str, str]]] = {
    "8/22(土)": [
        {
            "id": "b484",
            "name": "三原千砂子",
            "title": "三原千砂子様 駐車（自宅駐車場）",
            "body": (
                "往診車を自宅前に停めるのはご近所の迷惑になるため、ご自宅の駐車場を使ってください。"
                "入口にスライド式の柵があります。こちらで開けてかまいません。"
            ),
            "image": "assets/mihara_chisako_parking_gate.jpg",
        }
    ],
    "8/31(月)": [
        {
            "id": "b504",
            "name": "山﨑百子",
            "title": "山﨑百子様 自宅の鍵",
            "body": (
                "ご自身での鍵の施錠と開錠が困難なため、自宅入口の靴箱に鍵があります。"
                "開錠して入室の上、退室時は施錠をお願いします。"
            ),
            "image": "assets/yamazaki_momoko_house_key.png",
        }
    ],
}

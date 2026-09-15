from __future__ import annotations

import json
from typing import Protocol

RoutesMap = dict[str, dict[str, list[str]]]


class ScheduleRepository(Protocol):
  """割当の永続化。PlanetScale 実装は同インターフェースで差し替え。"""

  def has_routes(self, period_key: str) -> bool: ...

  def get_routes(self, period_key: str) -> RoutesMap: ...

  def replace_routes(
      self,
      period_key: str,
      routes: RoutesMap,
      *,
      source: str,
      note: str | None = None,
      title: str | None = None,
  ) -> None: ...

  def export_overrides_document(self, period_key: str) -> dict:
      """schedule_overrides.json 互換。"""
      ...


def routes_to_overrides_document(period_key: str, routes: RoutesMap) -> dict:
  from datetime import datetime, timezone

  return {
      "version": 1,
      "period_key": period_key,
      "updated_at": datetime.now(timezone.utc).isoformat(),
      "routes": routes,
  }


def overrides_document_to_routes(doc: dict) -> RoutesMap:
  routes = doc.get("routes") if isinstance(doc, dict) else None
  if not isinstance(routes, dict):
    return {}
  out: RoutesMap = {}
  for day_key, day_routes in routes.items():
    if not isinstance(day_routes, dict):
      continue
    out[str(day_key)] = {}
    for doctor, ids in day_routes.items():
      if isinstance(ids, list):
        out[str(day_key)][str(doctor)] = [str(x) for x in ids]
  return out


def routes_snapshot_json(routes: RoutesMap) -> str:
  return json.dumps(routes, ensure_ascii=False, sort_keys=True)

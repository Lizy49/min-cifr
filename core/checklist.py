"""Загрузка чек-листов обязательных разделов из data/checklists.json."""

import json
import os

_CHECKLIST_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "checklists.json")

_cache = None


def _load():
    global _cache
    if _cache is None:
        with open(_CHECKLIST_PATH, encoding="utf-8") as f:
            _cache = json.load(f)
    return _cache


def get_checklist(org_type):
    """Возвращает список разделов (словарей id/name/keywords/check_freshness) для типа организации."""
    return _load().get(org_type, [])


def available_org_types():
    return list(_load().keys())

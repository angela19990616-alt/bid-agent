from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


CONFIG_PATH = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "knowledge"
    / "default_case_library.json"
)


@lru_cache(maxsize=1)
def load_default_case_library() -> dict[str, Any]:
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if data.get("permission_scope") != "organization_private":
        raise ValueError("默认案例库必须保持机构私有。")
    if data.get("fact_usage") != "prohibited":
        raise ValueError("默认案例库必须禁止转化为企业事实。")
    active = [item for item in data.get("cases", []) if item.get("active")]
    if len(active) != 5:
        raise ValueError("当前默认案例库必须且只能启用五组真实案例。")
    return {**data, "cases": active}


def default_case_library_summary() -> dict[str, Any]:
    data = load_default_case_library()
    return {
        "count": len(data["cases"]),
        "scope": data["permission_scope"],
        "fact_usage": data["fact_usage"],
        "version": data["version"],
    }

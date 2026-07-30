"""Fast deterministic checks for a bounded, shortest-path AI workflow."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.model_routing import ModelRoutingRules  # noqa: E402
from app.workflows.controlled_pipeline import STAGES  # noqa: E402


def main() -> None:
    stages = list(STAGES)
    if len(stages) != len(set(stages)):
        raise SystemExit("受控工作流存在重复阶段。")

    routing = ModelRoutingRules.load()
    if routing.max_attempts > 3:
        raise SystemExit("模型路由超过三次尝试，不符合受控最短路径。")

    rule_files = sorted((ROOT / "config" / "rules").glob("*.json"))
    if not rule_files:
        raise SystemExit("未找到外部规则配置。")
    for path in rule_files:
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise SystemExit(f"规则文件必须是对象：{path.name}")

    print(
        f"架构策略通过：{len(stages)} 个唯一阶段，"
        f"模型最多 {routing.max_attempts} 次尝试，"
        f"{len(rule_files)} 份规则配置有效。"
    )


if __name__ == "__main__":
    main()

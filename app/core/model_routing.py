from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.config.settings import settings


@dataclass(frozen=True)
class ModelRoutingRules:
    max_attempts: int
    task_fallbacks: dict[str, list[str]]
    retryable_status_codes: frozenset[int]
    zero_usage_status_codes: frozenset[int]
    retryable_error_markers: tuple[str, ...]

    @classmethod
    def load(cls) -> "ModelRoutingRules":
        path = Path(settings.rules_root) / "model_routing.default.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("rule_type") != "model_routing":
            raise ValueError("模型路由规则类型不正确。")
        max_attempts = int(payload.get("max_attempts", 1))
        if not 1 <= max_attempts <= 3:
            raise ValueError("模型路由最多允许 3 次受控尝试。")
        return cls(
            max_attempts=max_attempts,
            task_fallbacks={
                str(task): [str(model) for model in models]
                for task, models in payload["task_fallbacks"].items()
            },
            retryable_status_codes=frozenset(
                int(code) for code in payload["retryable_status_codes"]
            ),
            zero_usage_status_codes=frozenset(
                int(code) for code in payload["zero_usage_status_codes"]
            ),
            retryable_error_markers=tuple(
                str(marker).lower()
                for marker in payload["retryable_error_markers"]
            ),
        )

    def models_for_task(self, task: str, primary: str) -> list[str]:
        candidates = [
            primary,
            *self.task_fallbacks.get(
                task,
                self.task_fallbacks.get("default", []),
            ),
        ]
        unique: list[str] = []
        for model in candidates:
            if model and model not in unique:
                unique.append(model)
        return unique[: self.max_attempts]

    def is_retryable(self, exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None)
        if status_code in self.retryable_status_codes:
            return True
        message = str(exc).lower()
        return any(
            marker in message for marker in self.retryable_error_markers
        )

    def known_zero_usage(self, exc: Exception) -> bool:
        return (
            getattr(exc, "status_code", None)
            in self.zero_usage_status_codes
        )

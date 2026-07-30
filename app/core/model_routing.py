from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from app.config.settings import settings


_HEALTH_LOCK = threading.Lock()
_COOLDOWN_UNTIL: dict[str, float] = {}
_PREFERRED_MODEL: dict[str, str] = {}


@dataclass(frozen=True)
class ModelRoutingRules:
    max_attempts: int
    max_billable_failures: int
    cooldown_seconds: int
    model_pool: tuple[dict, ...]
    task_fallbacks: dict[str, list[str]]
    retryable_status_codes: frozenset[int]
    zero_usage_status_codes: frozenset[int]
    zero_usage_error_markers: tuple[str, ...]
    retryable_error_markers: tuple[str, ...]

    @classmethod
    def load(cls) -> "ModelRoutingRules":
        path = Path(settings.rules_root) / "model_routing.default.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("rule_type") != "model_routing":
            raise ValueError("模型路由规则类型不正确。")
        max_attempts = int(payload.get("max_attempts", 1))
        if not 1 <= max_attempts <= 10:
            raise ValueError("模型路由最多允许 10 次受控尝试。")
        model_pool = tuple(payload.get("model_pool", []))
        model_ids = {
            str(item.get("id", "")).strip()
            for item in model_pool
            if isinstance(item, dict)
        }
        if len(model_ids) < 10:
            raise ValueError("模型池至少需要 10 个不同的候选模型。")
        max_billable_failures = int(
            payload.get("max_billable_failures", 2)
        )
        if not 1 <= max_billable_failures <= 3:
            raise ValueError("可能计费的模型失败最多允许 3 次。")
        cooldown_seconds = int(payload.get("cooldown_seconds", 1800))
        if not 60 <= cooldown_seconds <= 86400:
            raise ValueError("模型冷却时间必须在 60 秒到 24 小时之间。")
        return cls(
            max_attempts=max_attempts,
            max_billable_failures=max_billable_failures,
            cooldown_seconds=cooldown_seconds,
            model_pool=model_pool,
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
            zero_usage_error_markers=tuple(
                str(marker).lower()
                for marker in payload.get(
                    "zero_usage_error_markers", []
                )
            ),
            retryable_error_markers=tuple(
                str(marker).lower()
                for marker in payload["retryable_error_markers"]
            ),
        )

    def models_for_task(self, task: str, primary: str) -> list[str]:
        candidates = [
            *self.task_fallbacks.get(
                task,
                self.task_fallbacks.get("default", []),
            ),
            primary,
        ]
        unique: list[str] = []
        for model in candidates:
            if model and model not in unique:
                unique.append(model)
        now = time.monotonic()
        with _HEALTH_LOCK:
            available = [
                model
                for model in unique
                if _COOLDOWN_UNTIL.get(model, 0) <= now
            ]
        return available[: self.max_attempts]

    def output_limit(self, model: str, requested: int) -> int:
        for item in self.model_pool:
            if item.get("id") == model:
                return min(
                    requested,
                    int(item.get("max_output_tokens", requested)),
                )
        return requested

    def mark_failure(self, model: str, exc: Exception) -> None:
        if not self.known_zero_usage(exc):
            return
        with _HEALTH_LOCK:
            _COOLDOWN_UNTIL[model] = (
                time.monotonic() + self.cooldown_seconds
            )
            for task, preferred in list(_PREFERRED_MODEL.items()):
                if preferred == model:
                    _PREFERRED_MODEL.pop(task, None)

    @staticmethod
    def mark_success(task: str, model: str) -> None:
        with _HEALTH_LOCK:
            _COOLDOWN_UNTIL.pop(model, None)

    @staticmethod
    def reset_health() -> None:
        with _HEALTH_LOCK:
            _COOLDOWN_UNTIL.clear()
            _PREFERRED_MODEL.clear()

    def is_retryable(self, exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None)
        if status_code in self.retryable_status_codes:
            return True
        message = str(exc).lower()
        return any(
            marker in message for marker in self.retryable_error_markers
        )

    def known_zero_usage(self, exc: Exception) -> bool:
        if (
            getattr(exc, "status_code", None)
            in self.zero_usage_status_codes
        ):
            return True
        message = str(exc).lower()
        return any(
            marker in message
            for marker in self.zero_usage_error_markers
        )

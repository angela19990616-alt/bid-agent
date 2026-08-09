from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from app.config.settings import settings


@dataclass(frozen=True)
class PrivacyRule:
    category: str
    pattern: re.Pattern[str]
    value_group: int


@dataclass(frozen=True)
class PrivacySanitizer:
    rules: tuple[PrivacyRule, ...]

    @classmethod
    def load(cls) -> "PrivacySanitizer":
        path = Path(settings.rules_root) / "privacy_redaction.default.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("rule_type") != "privacy_redaction":
            raise ValueError("隐私脱敏规则类型不正确。")
        return cls(
            rules=tuple(
                PrivacyRule(
                    category=str(item["category"]),
                    pattern=re.compile(str(item["pattern"])),
                    value_group=int(item.get("value_group", 0)),
                )
                for item in payload.get("rules", [])
                if item.get("enabled", True)
            )
        )

    def sanitize_text(
        self, text: str, replacements: dict[str, str] | None = None
    ) -> tuple[str, dict[str, str]]:
        mapping = replacements if replacements is not None else {}
        value_tokens = {value: token for token, value in mapping.items()}
        counters: dict[str, int] = {}

        def token_for(category: str, value: str) -> str:
            if value in value_tokens:
                return value_tokens[value]
            counters[category] = counters.get(category, 0) + 1
            token = f"【{category}_{counters[category]}】"
            while token in mapping:
                counters[category] += 1
                token = f"【{category}_{counters[category]}】"
            mapping[token] = value
            value_tokens[value] = token
            return token

        result = text
        for rule in self.rules:
            def replace(match: re.Match[str]) -> str:
                value = match.group(rule.value_group)
                token = token_for(rule.category, value)
                if rule.value_group == 0:
                    return token
                start, end = match.span(rule.value_group)
                relative_start = start - match.start()
                relative_end = end - match.start()
                original = match.group(0)
                return (
                    original[:relative_start]
                    + token
                    + original[relative_end:]
                )

            result = rule.pattern.sub(replace, result)
        return result, mapping

    def sanitize_messages(
        self, messages: list[dict[str, str]]
    ) -> tuple[list[dict[str, str]], dict[str, str]]:
        mapping: dict[str, str] = {}
        sanitized: list[dict[str, str]] = []
        for message in messages:
            content, mapping = self.sanitize_text(
                str(message.get("content", "")), mapping
            )
            sanitized.append({**message, "content": content})
        return sanitized, mapping

    @staticmethod
    def restore(text: str, mapping: dict[str, str]) -> str:
        restored = text
        for token, value in mapping.items():
            restored = restored.replace(token, value)
        return restored

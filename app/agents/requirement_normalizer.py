from __future__ import annotations

import re
from dataclasses import dataclass, replace

from app.agents.requirement_agent import AgentRequirement


INCLUDE_PATTERN = re.compile(
    r"^(?P<prefix>.+?)(?:包括|包含|具体包括|主要包括)[：:]?"
    r"(?P<body>.+)$"
)
LIST_SEPARATOR = re.compile(r"[；;、]")
TRAILING_WORDS = re.compile(r"(?:等内容|等方面|等要求)[。.]?$")


@dataclass(frozen=True)
class NormalizationEvent:
    source_id: object
    operation: str
    input_text: str
    output_texts: tuple[str, ...]


@dataclass(frozen=True)
class NormalizationResult:
    items: tuple[AgentRequirement, ...]
    events: tuple[NormalizationEvent, ...]


class ResponseItemNormalizer:
    """Normalize and cautiously split extracted response items."""

    def normalize(
        self,
        items: list[AgentRequirement],
    ) -> NormalizationResult:
        normalized: list[AgentRequirement] = []
        events: list[NormalizationEvent] = []
        for item in items:
            cleaned = self._clean(item.normalized_text)
            current = replace(
                item,
                title=self._clean(item.title),
                normalized_text=cleaned,
                quote=self._clean(item.quote),
            )
            split_items = self._split_inclusion(current)
            normalized.extend(split_items)
            operation = (
                "split"
                if len(split_items) > 1
                else "standardize"
                if cleaned != item.normalized_text
                else "unchanged"
            )
            events.append(
                NormalizationEvent(
                    source_id=item.source_id,
                    operation=operation,
                    input_text=item.normalized_text,
                    output_texts=tuple(
                        value.normalized_text for value in split_items
                    ),
                )
            )
        return NormalizationResult(
            items=tuple(normalized),
            events=tuple(events),
        )

    @classmethod
    def _split_inclusion(
        cls,
        item: AgentRequirement,
    ) -> list[AgentRequirement]:
        match = INCLUDE_PATTERN.match(item.normalized_text)
        if not match:
            return [item]
        raw_parts = [
            TRAILING_WORDS.sub("", part.strip(" ，,。"))
            for part in LIST_SEPARATOR.split(match.group("body"))
        ]
        parts = [
            part
            for part in raw_parts
            if 4 <= len(part) <= 160
        ]
        if len(parts) < 2 or len(parts) > 8:
            return [item]
        subject = cls._subject(match.group("prefix"))
        return [
            replace(
                item,
                title=part[:80],
                normalized_text=f"{subject}应包含{part}。",
            )
            for part in parts
        ]

    @staticmethod
    def _subject(prefix: str) -> str:
        if "服务方案" in prefix:
            return "服务方案"
        if "技术方案" in prefix:
            return "技术方案"
        return "响应方案"

    @staticmethod
    def _clean(value: str) -> str:
        compact = re.sub(r"[\t\r ]+", " ", value or "")
        compact = re.sub(r"\n{2,}", "\n", compact)
        return compact.strip()

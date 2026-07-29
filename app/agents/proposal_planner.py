from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.rules.engine import RuleDocument, RuleEngine


@dataclass(frozen=True)
class PlannedChapter:
    title: str
    requirement_ids: tuple[UUID, ...]
    sort_order: int


class ProposalPlanner:
    def plan(
        self,
        requirements: list[dict],
        rules: RuleDocument | None = None,
    ) -> list[PlannedChapter]:
        active = rules or RuleEngine().load("writing")
        chapter_order = active.content["chapter_order"]
        grouped: dict[str, list[UUID]] = {}
        for item in requirements:
            if not item.get("need_generation"):
                continue
            title = item.get("target_chapter") or chapter_order[0]
            grouped.setdefault(title, []).append(item["id"])

        ordered_titles = [
            title for title in chapter_order if title in grouped
        ]
        ordered_titles.extend(
            title for title in grouped if title not in ordered_titles
        )
        return [
            PlannedChapter(
                title=title,
                requirement_ids=tuple(dict.fromkeys(grouped[title])),
                sort_order=index,
            )
            for index, title in enumerate(ordered_titles, start=1)
        ]

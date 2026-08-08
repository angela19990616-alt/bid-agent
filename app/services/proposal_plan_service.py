from __future__ import annotations

import re
from uuid import UUID

from psycopg.rows import dict_row

from app.agents.proposal_planner import ProposalPlanner
from app.database.db import connect
from app.rules.engine import RuleDocument, RuleEngine
from app.services.section_service import SectionService


class ProposalPlanError(Exception):
    pass


class ProposalPlanService:
    def __init__(
        self,
        planner: ProposalPlanner | None = None,
        rule_engine: RuleEngine | None = None,
    ):
        self.planner = planner or ProposalPlanner()
        self.rule_engine = rule_engine or RuleEngine()

    def create_recommended_outline(
        self,
        project_id: UUID,
        rules: RuleDocument | None = None,
    ) -> list[dict]:
        template_rules = self.rule_engine.load("template_generation")
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id, normalized_text,
                           proposal_mapping AS proposal_chapter,
                           proposal_mapping AS target_chapter,
                           need_generation
                    FROM requirements
                    WHERE project_id = %s
                      AND status <> 'rejected'
                      AND response_action = 'write_into_proposal'
                      AND proposal_relevance = TRUE
                      AND target_chapter IS NOT NULL
                    ORDER BY created_at, id
                    """,
                    (project_id,),
                )
                requirements = cursor.fetchall()
                cursor.execute(
                    """
                    SELECT generation_mode, template_descriptor
                    FROM proposal_generation_profiles
                    WHERE project_id = %s
                    """,
                    (project_id,),
                )
                generation_profile = cursor.fetchone() or {}
                cursor.execute(
                    """
                    SELECT normalized_text, quote
                    FROM requirements
                    WHERE project_id = %s
                      AND status <> 'rejected'
                      AND (
                        normalized_text ~
                          '目录|章节|编制|格式|必须包括|应包括'
                        OR quote ~
                          '目录|章节|编制|格式|必须包括|应包括'
                      )
                    ORDER BY created_at
                    """,
                    (project_id,),
                )
                format_constraints = cursor.fetchall()
                if generation_profile.get("generation_mode") == "strict_template":
                    chapters = self._template_chapters(
                        generation_profile.get("template_descriptor") or {},
                        requirements,
                        template_rules.content.get("policies", {}),
                    )
                else:
                    active_rules = rules or self.rule_engine.load("writing")
                    chapters = self.planner.plan(
                        requirements,
                        active_rules,
                        format_constraints=format_constraints,
                    )
                # A detected response template can be field/table-only. It is
                # still a valid strict-fill project even when there is no
                # long-form chapter for the model to write. Only the true
                # no-template branch requires a generated writing outline.
                if (
                    not chapters
                    and generation_profile.get("generation_mode")
                    != "strict_template"
                ):
                    raise ProposalPlanError(
                        "未提取到可用于技术方案撰写的要求。"
                    )
                cursor.execute(
                    """
                    DELETE FROM sections
                    WHERE project_id = %s
                      AND current_version_id IS NULL
                    """,
                    (project_id,),
                )
                for chapter in chapters:
                    title = (
                        chapter["title"] if isinstance(chapter, dict)
                        else chapter.title
                    )
                    sort_order = (
                        chapter["sort_order"] if isinstance(chapter, dict)
                        else chapter.sort_order
                    )
                    requirement_ids = (
                        chapter["requirement_ids"] if isinstance(chapter, dict)
                        else chapter.requirement_ids
                    )
                    cursor.execute(
                        """
                        INSERT INTO sections (
                            project_id, title, sort_order, is_recommended
                        )
                        VALUES (%s, %s, %s, TRUE)
                        RETURNING id
                        """,
                        (project_id, title, sort_order),
                    )
                    section_id = cursor.fetchone()["id"]
                    cursor.executemany(
                        """
                        INSERT INTO section_requirements (
                            section_id, requirement_id
                        )
                        VALUES (%s, %s)
                        """,
                        [
                            (section_id, requirement_id)
                            for requirement_id in requirement_ids
                        ],
                    )
                cursor.execute(
                    """
                    UPDATE projects
                    SET status = 'outline_ready', updated_at = NOW()
                    WHERE id = %s
                    """,
                    (project_id,),
                )
        return SectionService().list(project_id)

    @classmethod
    def _template_chapters(
        cls,
        descriptor: dict,
        requirements: list[dict],
        policies: dict,
    ) -> list[dict]:
        """Use detected template headings as the only writing skeleton."""
        outline = descriptor.get("outline") or []
        include = tuple(policies.get("writing_section_patterns") or ())
        exclude = tuple(policies.get("non_writing_section_patterns") or ())
        anchors = [
            item for item in outline
            if any(pattern in item.get("title", "") for pattern in include)
            and not any(pattern in item.get("title", "") for pattern in exclude)
        ]
        if not anchors:
            return []

        selected: list[dict] = []
        for anchor in anchors:
            if anchor not in selected:
                selected.append(anchor)
            anchor_index = outline.index(anchor)
            anchor_level = int(anchor.get("level") or 1)
            for item in outline[anchor_index + 1:]:
                if int(item.get("level") or 1) <= anchor_level:
                    break
                if not any(
                    pattern in item.get("title", "") for pattern in exclude
                ):
                    selected.append(item)

        # A parent heading already exists in the original template. When it
        # has concrete child headings, generate only those leaf sections so
        # the model does not invent a second generic parent-body chapter.
        leaf_items = []
        for index, item in enumerate(selected):
            level = int(item.get("level") or 1)
            next_item = selected[index + 1] if index + 1 < len(selected) else None
            if next_item and int(next_item.get("level") or 1) > level:
                continue
            leaf_items.append(item)

        unique = []
        seen_titles: set[str] = set()
        for item in leaf_items:
            title = str(item.get("title") or "").strip()
            if title and title not in seen_titles:
                unique.append(item)
                seen_titles.add(title)

        assignments: dict[str, list[UUID]] = {
            item["title"]: [] for item in unique
        }
        for requirement in requirements:
            target = str(requirement.get("target_chapter") or "")
            normalized = str(requirement.get("normalized_text") or "")
            best = max(
                unique,
                key=lambda item: cls._title_match_score(
                    item["title"], target, normalized
                ),
            )
            assignments[best["title"]].append(requirement["id"])

        return [
            {
                "title": item["title"],
                "sort_order": index,
                "requirement_ids": assignments[item["title"]],
            }
            for index, item in enumerate(unique, start=1)
        ]

    @staticmethod
    def _title_match_score(title: str, target: str, text: str) -> int:
        clean_title = re.sub(r"^[\d.．、（）()一二三四五六七八九十\s]+", "", title)
        score = 0
        if target and (target in title or clean_title in target):
            score += 100
        keywords = set(re.findall(r"[\u4e00-\u9fff]{2,6}", clean_title))
        score += sum(5 for keyword in keywords if keyword in target)
        score += sum(1 for keyword in keywords if keyword in text)
        return score

    def reconcile_requirement_feedback(
        self,
        project_id: UUID,
        requirement_id: UUID,
    ) -> list[dict]:
        """Keep an ungenerated outline in sync with human feedback."""
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT status, response_action, proposal_mapping,
                           proposal_relevance
                    FROM requirements
                    WHERE project_id = %s AND id = %s
                    """,
                    (project_id, requirement_id),
                )
                requirement = cursor.fetchone()
                if requirement is None:
                    return SectionService().list(project_id)

                cursor.execute(
                    """
                    DELETE FROM section_requirements
                    USING sections
                    WHERE section_requirements.section_id = sections.id
                      AND section_requirements.requirement_id = %s
                      AND sections.project_id = %s
                      AND sections.current_version_id IS NULL
                    """,
                    (requirement_id, project_id),
                )

                eligible = (
                    requirement["status"] != "rejected"
                    and requirement["response_action"]
                    == "write_into_proposal"
                    and requirement.get("proposal_relevance", True)
                    and requirement["proposal_mapping"] is not None
                )
                if eligible:
                    cursor.execute(
                        """
                        SELECT id
                        FROM sections
                        WHERE project_id = %s
                          AND title = %s
                          AND current_version_id IS NULL
                        ORDER BY created_at
                        LIMIT 1
                        """,
                        (
                            project_id,
                            requirement["proposal_mapping"],
                        ),
                    )
                    section = cursor.fetchone()
                    if section is None:
                        cursor.execute(
                            """
                            INSERT INTO sections (
                                project_id, title, sort_order, is_recommended
                            )
                            SELECT %s, %s, COALESCE(MAX(sort_order), 0) + 1,
                                   TRUE
                            FROM sections
                            WHERE project_id = %s
                            RETURNING id
                            """,
                            (
                                project_id,
                                requirement["proposal_mapping"],
                                project_id,
                            ),
                        )
                        section = cursor.fetchone()
                    cursor.execute(
                        """
                        INSERT INTO section_requirements (
                            section_id, requirement_id
                        )
                        VALUES (%s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        (section["id"], requirement_id),
                    )

                cursor.execute(
                    """
                    DELETE FROM sections
                    WHERE project_id = %s
                      AND current_version_id IS NULL
                      AND NOT EXISTS (
                          SELECT 1
                          FROM section_requirements
                          WHERE section_requirements.section_id = sections.id
                      )
                    """,
                    (project_id,),
                )
        return SectionService().list(project_id)

    def replace_outline(
        self,
        project_id: UUID,
        chapters: list[dict],
    ) -> list[dict]:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT 1 FROM sections
                    WHERE project_id = %s AND current_version_id IS NOT NULL
                    LIMIT 1
                    """,
                    (project_id,),
                )
                if cursor.fetchone():
                    raise ProposalPlanError(
                        "已有章节开始生成，不能整体替换目录。"
                    )
                requirement_ids = [
                    requirement_id
                    for chapter in chapters
                    for requirement_id in chapter["requirement_ids"]
                ]
                if not requirement_ids:
                    raise ProposalPlanError("目录至少需要关联一条技术要求。")
                cursor.execute(
                    """
                    SELECT id FROM requirements
                    WHERE project_id = %s
                      AND id = ANY(%s)
                      AND status <> 'rejected'
                      AND response_action = 'write_into_proposal'
                      AND proposal_relevance = TRUE
                      AND proposal_mapping IS NOT NULL
                    """,
                    (project_id, list(dict.fromkeys(requirement_ids))),
                )
                eligible = {row["id"] for row in cursor.fetchall()}
                filtered_chapters = self._filter_chapters(
                    chapters,
                    eligible,
                )
                if not filtered_chapters:
                    raise ProposalPlanError(
                        "当前没有需要写入技术方案的内容。"
                    )
                cursor.execute(
                    "DELETE FROM sections WHERE project_id = %s",
                    (project_id,),
                )
                for index, chapter in enumerate(
                    filtered_chapters,
                    start=1,
                ):
                    cursor.execute(
                        """
                        INSERT INTO sections (
                            project_id, title, sort_order, is_recommended
                        )
                        VALUES (%s, %s, %s, FALSE)
                        RETURNING id
                        """,
                        (project_id, chapter["title"].strip(), index),
                    )
                    section_id = cursor.fetchone()["id"]
                    cursor.executemany(
                        """
                        INSERT INTO section_requirements (
                            section_id, requirement_id
                        )
                        VALUES (%s, %s)
                        """,
                        [
                            (section_id, requirement_id)
                            for requirement_id in dict.fromkeys(
                                chapter["requirement_ids"]
                            )
                        ],
                    )
        return SectionService().list(project_id)

    @staticmethod
    def _filter_chapters(
        chapters: list[dict],
        eligible: set[UUID],
    ) -> list[dict]:
        filtered = [
            {
                **chapter,
                "requirement_ids": [
                    requirement_id
                    for requirement_id in dict.fromkeys(
                        chapter["requirement_ids"]
                    )
                    if requirement_id in eligible
                ],
            }
            for chapter in chapters
        ]
        return [chapter for chapter in filtered if chapter["requirement_ids"]]

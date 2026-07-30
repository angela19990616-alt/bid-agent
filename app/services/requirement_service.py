from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from difflib import SequenceMatcher
from uuid import UUID

from psycopg.rows import dict_row

from app.agents.requirement_agent import (
    AgentRequirement,
    RequirementAgent,
    RequirementAgentError,
)
from app.agents.requirement_normalizer import (
    NormalizationEvent,
    ResponseItemNormalizer,
)
from app.agents.requirement_classifier import (
    ClassificationReviewer,
    ClassifiedRequirement,
    RequirementClassifier,
)
from app.agents.output_quality import ReviewedDebugPipeline
from app.agents.requirement_reviewer import (
    RequirementReviewer,
    ReviewedRequirement,
)
from app.database.db import connect
from app.rules.engine import RuleDocument, RuleEngine
from app.services.model_budget_service import ModelBudgetExceeded
from app.workflows.controlled_pipeline import ControlledPipeline


@dataclass(frozen=True)
class Candidate:
    source_ids: tuple[UUID, ...]
    title: str
    normalized_text: str
    quote: str
    requirement_type: str
    importance: str
    confidence: float
    scoring_relation: str
    classification_confidence: float
    classification_conflict: bool
    classification_notes: str
    knowledge_support_required: bool
    proposal_relevance: str
    proposal_chapter: str | None
    target_chapter: str | None
    need_generation: bool
    fingerprint: str


class RequirementNotFoundError(Exception):
    pass


class RequirementValidationError(Exception):
    pass


class RequirementExtractionError(Exception):
    pass


class RequirementService:
    SOURCE_MISMATCH_MARKER = "human_feedback:source_mismatch"

    def __init__(
        self,
        requirement_agent: RequirementAgent | None = None,
        reviewer: RequirementReviewer | None = None,
        rule_engine: RuleEngine | None = None,
        classifier: RequirementClassifier | None = None,
        classification_reviewer: ClassificationReviewer | None = None,
        normalizer: ResponseItemNormalizer | None = None,
        quality_pipeline: ReviewedDebugPipeline | None = None,
    ):
        self.requirement_agent = requirement_agent
        self.reviewer = reviewer or RequirementReviewer()
        self.classifier = classifier or RequirementClassifier()
        self.classification_reviewer = (
            classification_reviewer or ClassificationReviewer()
        )
        self.normalizer = normalizer or ResponseItemNormalizer()
        self.quality_pipeline = quality_pipeline or ReviewedDebugPipeline()
        self.rule_engine = rule_engine or RuleEngine()

    def extract(
        self,
        project_id: UUID,
        document_ids: list[UUID],
        rules: RuleDocument | None = None,
        classification_rules: RuleDocument | None = None,
        workflow_run_id: UUID | None = None,
    ) -> tuple[int, int]:
        sources = self._load_sources(project_id, document_ids)
        if not sources:
            raise RequirementValidationError(
                "没有找到可用于提取的已解析文件。"
            )
        try:
            active_rules = rules or self.rule_engine.load("extraction")
            agent_items = (
                self.requirement_agent or RequirementAgent()
            ).extract(
                sources,
                active_rules,
                workflow_run_id=workflow_run_id,
                project_id=project_id,
            )
        except ModelBudgetExceeded as exc:
            raise RequirementExtractionError(str(exc)) from exc
        except RequirementAgentError as exc:
            raise RequirementExtractionError(
                "Requirement Agent 未能完成提取，请检查模型配置后重试。"
            ) from exc
        normalized = self.normalizer.normalize(agent_items)
        if workflow_run_id is not None:
            ControlledPipeline().record(
                workflow_run_id,
                "response_item_normalizer",
                details={
                    "input_count": len(agent_items),
                    "output_count": len(normalized.items),
                    "split_count": sum(
                        event.operation == "split"
                        for event in normalized.events
                    ),
                },
            )
        self._record_normalization_events(
            project_id,
            workflow_run_id,
            normalized.events,
        )
        active_classification_rules = (
            classification_rules
            or self.rule_engine.load("classification")
        )
        project_context = self._load_project_context(
            project_id, document_ids
        )
        if workflow_run_id is not None:
            ControlledPipeline().record(
                workflow_run_id,
                "proposal_classification",
                rule_snapshot=active_classification_rules.snapshot(),
                details={
                    "modules": [
                        "classification_agent",
                        "classification_reviewer",
                        "output_review_agent",
                        "debug_agent",
                        "post_debug_review",
                    ],
                    "execution": "single_bounded_pass",
                },
            )
        try:
            classified = self.classifier.classify(
                list(normalized.items),
                active_classification_rules,
                workflow_run_id=workflow_run_id,
                project_context=project_context,
            )
        except ModelBudgetExceeded as exc:
            raise RequirementExtractionError(str(exc)) from exc
        reviewed = self.classification_reviewer.review(
            classified,
            active_classification_rules,
            project_context=project_context,
        )
        quality_checked = self.quality_pipeline.run(reviewed)
        candidates = self._exclude_known_source_mismatches(
            self._deduplicate(quality_checked)
        )[:200]

        created = 0
        skipped = 0
        with connect() as conn:
            with conn.cursor() as cursor:
                self._remove_unconfirmed_for_documents(
                    cursor,
                    project_id,
                    document_ids,
                )
                for candidate in candidates:
                    cursor.execute(
                        """
                        INSERT INTO requirements (
                            project_id, requirement_type, title,
                            normalized_text, quote, importance, confidence,
                            scoring_relation, classification_confidence,
                            classification_conflict, classification_notes,
                            knowledge_support_required, proposal_relevance,
                            proposal_chapter, target_chapter,
                            need_generation, fingerprint
                        )
                        VALUES (
                            %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s
                        )
                        ON CONFLICT (project_id, fingerprint) DO NOTHING
                        RETURNING id
                        """,
                        (
                            project_id,
                            candidate.requirement_type,
                            candidate.title,
                            candidate.normalized_text,
                            candidate.quote,
                            candidate.importance,
                            candidate.confidence,
                            candidate.scoring_relation,
                            candidate.classification_confidence,
                            candidate.classification_conflict,
                            candidate.classification_notes,
                            candidate.knowledge_support_required,
                            candidate.proposal_relevance,
                            candidate.proposal_chapter,
                            candidate.target_chapter,
                            candidate.need_generation,
                            candidate.fingerprint,
                        ),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        skipped += 1
                        continue
                    for source_id in candidate.source_ids:
                        cursor.execute(
                            """
                            INSERT INTO requirement_sources (
                                requirement_id, source_chunk_id
                            )
                            VALUES (%s, %s)
                            ON CONFLICT DO NOTHING
                            """,
                            (row[0], source_id),
                        )
                    created += 1
                cursor.execute(
                    """
                    UPDATE projects
                    SET status = 'reviewing_requirements', updated_at = NOW()
                    WHERE id = %s
                    """,
                    (project_id,),
                )
        return created, skipped

    @staticmethod
    def _load_project_context(
        project_id: UUID,
        document_ids: list[UUID],
    ) -> str:
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT projects.name,
                           COALESCE(string_agg(documents.filename, ' '), '')
                    FROM projects
                    LEFT JOIN documents
                      ON documents.project_id = projects.id
                     AND documents.public_id = ANY(%s)
                    WHERE projects.id = %s
                    GROUP BY projects.id
                    """,
                    (document_ids, project_id),
                )
                row = cursor.fetchone()
        return " ".join(str(value or "") for value in row) if row else ""

    @staticmethod
    def _record_normalization_events(
        project_id: UUID,
        workflow_run_id: UUID | None,
        events: tuple[NormalizationEvent, ...],
    ) -> None:
        if not events:
            return
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO requirement_normalization_events (
                        workflow_run_id, project_id, source_chunk_id,
                        operation, input_text, output_texts
                    )
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    [
                        (
                            workflow_run_id,
                            project_id,
                            event.source_id,
                            event.operation,
                            event.input_text,
                            json.dumps(
                                event.output_texts,
                                ensure_ascii=False,
                            ),
                        )
                        for event in events
                    ],
                )

    def list(
        self,
        project_id: UUID,
        *,
        status: str | None = None,
        requirement_type: str | None = None,
        document_id: UUID | None = None,
        proposal_relevance: str | None = None,
        need_generation: bool | None = None,
    ) -> list[dict]:
        filters = ["requirements.project_id = %s"]
        params: list[object] = [project_id]
        if status:
            filters.append("requirements.status = %s")
            params.append(status)
        if requirement_type:
            filters.append("requirements.requirement_type = %s")
            params.append(requirement_type)
        if document_id:
            filters.append("documents.public_id = %s")
            params.append(document_id)
        if proposal_relevance:
            filters.append("requirements.proposal_relevance = %s")
            params.append(proposal_relevance)
        if need_generation is not None:
            filters.append("requirements.need_generation = %s")
            params.append(need_generation)
        sql = self._select_sql() + " WHERE " + " AND ".join(filters)
        sql += " ORDER BY requirements.updated_at DESC"
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(sql, params)
                return self._group_rows(cursor.fetchall())

    def update(
        self,
        project_id: UUID,
        requirement_id: UUID,
        changes: dict,
    ) -> dict:
        allowed = {
            "title": "title",
            "normalized_text": "normalized_text",
            "type": "requirement_type",
            "importance": "importance",
            "status": "status",
            "proposal_relevance": "proposal_relevance",
            "target_chapter": "target_chapter",
            "proposal_chapter": "proposal_chapter",
            "scoring_relation": "scoring_relation",
            "need_generation": "need_generation",
        }
        values = {
            allowed[key]: value.strip() if isinstance(value, str) else value
            for key, value in changes.items()
            if value is not None and key in allowed
        }
        if values.get("status") == "confirmed":
            with connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT 1
                        FROM requirement_sources
                        JOIN requirements
                            ON requirements.id =
                               requirement_sources.requirement_id
                        WHERE requirements.project_id = %s
                          AND requirements.id = %s
                        """,
                        (project_id, requirement_id),
                    )
                    if cursor.fetchone() is None:
                        raise RequirementValidationError(
                            "没有有效原文来源的要求不能确认。"
                        )
        if values:
            assignments = ", ".join(f"{key} = %s" for key in values)
            params = [*values.values(), project_id, requirement_id]
            with connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE requirements
                        SET {assignments}, updated_at = NOW()
                        WHERE project_id = %s AND id = %s
                        """,
                        params,
                    )
                    if cursor.rowcount == 0:
                        raise RequirementNotFoundError(str(requirement_id))
        return self.get(project_id, requirement_id)

    def reject(self, project_id: UUID, requirement_id: UUID) -> None:
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE requirements
                    SET status = 'rejected', updated_at = NOW()
                    WHERE project_id = %s AND id = %s
                    """,
                    (project_id, requirement_id),
                )
                if cursor.rowcount == 0:
                    raise RequirementNotFoundError(str(requirement_id))

    def record_feedback(
        self,
        project_id: UUID,
        requirement_id: UUID,
        feedback: str,
    ) -> dict:
        if feedback not in {
            "pending", "confirmed", "not_needed", "source_mismatch"
        }:
            raise RequirementValidationError("不支持的人工确认结果。")
        if feedback == "confirmed":
            return self.update(
                project_id, requirement_id, {"status": "confirmed"}
            )
        if feedback == "pending":
            return self.update(
                project_id, requirement_id, {"status": "pending"}
            )

        notes = None
        conflict = False
        if feedback == "source_mismatch":
            notes = self.SOURCE_MISMATCH_MARKER
            conflict = True
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE requirements
                    SET status = 'rejected',
                        classification_conflict = %s,
                        classification_notes = %s,
                        updated_at = NOW()
                    WHERE project_id = %s AND id = %s
                    """,
                    (conflict, notes, project_id, requirement_id),
                )
                if cursor.rowcount == 0:
                    raise RequirementNotFoundError(str(requirement_id))
        return self.get(project_id, requirement_id)

    def _exclude_known_source_mismatches(
        self,
        candidates: list[Candidate],
    ) -> list[Candidate]:
        """Suppress only exact text previously marked as not matching source."""
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT normalized_text
                    FROM requirements
                    WHERE status = 'rejected'
                      AND classification_notes = %s
                    """,
                    (self.SOURCE_MISMATCH_MARKER,),
                )
                rejected = {
                    self._feedback_key(row[0]) for row in cursor.fetchall()
                }
        return [
            item
            for item in candidates
            if self._feedback_key(item.normalized_text) not in rejected
        ]

    @staticmethod
    def _feedback_key(text: str) -> str:
        return re.sub(r"\s+", "", text).casefold()

    def get(self, project_id: UUID, requirement_id: UUID) -> dict:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    self._select_sql()
                    + """
                    WHERE requirements.project_id = %s
                      AND requirements.id = %s
                    """,
                    (project_id, requirement_id),
                )
                rows = cursor.fetchall()
        if not rows:
            raise RequirementNotFoundError(str(requirement_id))
        return self._group_rows(rows)[0]

    @staticmethod
    def _load_sources(project_id: UUID, document_ids: list[UUID]):
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT
                        source_chunks.id,
                        source_chunks.content,
                        source_chunks.locator_kind,
                        source_chunks.page_no,
                        source_chunks.paragraph_start,
                        source_chunks.paragraph_end
                    FROM source_chunks
                    JOIN documents
                        ON documents.id = source_chunks.document_id
                    WHERE documents.project_id = %s
                      AND documents.public_id = ANY(%s)
                      AND documents.status = 'parsed'
                    ORDER BY documents.id, source_chunks.chunk_index
                    """,
                    (project_id, document_ids),
                )
                return cursor.fetchall()

    @staticmethod
    def _deduplicate(
        items: list[
            ClassifiedRequirement | ReviewedRequirement | AgentRequirement
        ],
    ) -> list[Candidate]:
        merged: list[dict] = []
        for raw_item in items:
            if isinstance(raw_item, ClassifiedRequirement):
                classified = raw_item
                item = classified.item
                proposal_chapter = classified.proposal_chapter
                need_generation = proposal_chapter is not None
                relevance = (
                    "high"
                    if classified.importance in {"critical", "high"}
                    or classified.scoring_relation == "high_score_item"
                    else "medium" if need_generation else "low"
                )
            else:
                reviewed = (
                    raw_item
                    if isinstance(raw_item, ReviewedRequirement)
                    else RequirementReviewer().review_one(raw_item)
                )
                item = reviewed.item
                classified = RequirementClassifier.classify_by_rules(item)
                proposal_chapter = reviewed.target_chapter
                need_generation = reviewed.need_generation
                relevance = reviewed.proposal_relevance
            canonical = RequirementService._canonical(
                item.normalized_text
            )
            duplicate = next(
                (
                    current
                    for current in merged
                    if RequirementService._is_semantic_duplicate(
                        canonical,
                        current["canonical"],
                        item.title,
                        current["title"],
                    )
                ),
                None,
            )
            if duplicate is None:
                merged.append(
                    {
                        "canonical": canonical,
                        "source_ids": [item.source_id],
                        "title": item.title,
                        "normalized_text": item.normalized_text,
                        "quote": item.quote,
                        "requirement_type": classified.requirement_type,
                        "importance": classified.importance,
                        "confidence": item.confidence,
                        "scoring_relation": classified.scoring_relation,
                        "classification_confidence": classified.confidence,
                        "classification_conflict": classified.conflict,
                        "classification_notes": classified.rationale,
                        "knowledge_support_required": (
                            classified.knowledge_support_required
                        ),
                        "proposal_relevance": relevance,
                        "proposal_chapter": proposal_chapter,
                        "target_chapter": proposal_chapter,
                        "need_generation": need_generation,
                    }
                )
                continue
            if item.source_id not in duplicate["source_ids"]:
                duplicate["source_ids"].append(item.source_id)
            if item.confidence > duplicate["confidence"]:
                duplicate.update(
                    {
                        "canonical": canonical,
                        "title": item.title,
                        "normalized_text": item.normalized_text,
                        "quote": item.quote,
                        "requirement_type": classified.requirement_type,
                        "importance": classified.importance,
                        "confidence": item.confidence,
                        "scoring_relation": classified.scoring_relation,
                        "classification_confidence": classified.confidence,
                        "classification_conflict": classified.conflict,
                        "classification_notes": classified.rationale,
                        "knowledge_support_required": (
                            classified.knowledge_support_required
                        ),
                        "proposal_relevance": relevance,
                        "proposal_chapter": proposal_chapter,
                        "target_chapter": proposal_chapter,
                        "need_generation": need_generation,
                    }
                )
        return [
            Candidate(
                source_ids=tuple(item["source_ids"]),
                title=item["title"],
                normalized_text=item["normalized_text"],
                quote=item["quote"],
                requirement_type=item["requirement_type"],
                importance=item["importance"],
                confidence=item["confidence"],
                scoring_relation=item["scoring_relation"],
                classification_confidence=item[
                    "classification_confidence"
                ],
                classification_conflict=item["classification_conflict"],
                classification_notes=item["classification_notes"],
                knowledge_support_required=item[
                    "knowledge_support_required"
                ],
                proposal_relevance=item["proposal_relevance"],
                proposal_chapter=item["proposal_chapter"],
                target_chapter=item["target_chapter"],
                need_generation=item["need_generation"],
                fingerprint=hashlib.sha256(
                    item["canonical"].encode()
                ).hexdigest(),
            )
            for item in merged
            if item["canonical"]
        ]

    @staticmethod
    def _is_semantic_duplicate(
        left: str,
        right: str,
        left_title: str,
        right_title: str,
    ) -> bool:
        if left == right:
            return True
        body_similarity = SequenceMatcher(None, left, right).ratio()
        title_similarity = SequenceMatcher(
            None,
            RequirementService._canonical(left_title),
            RequirementService._canonical(right_title),
        ).ratio()
        return body_similarity >= 0.86 or (
            title_similarity >= 0.9 and body_similarity >= 0.62
        ) or (
            title_similarity >= 0.98 and body_similarity >= 0.5
        )

    @staticmethod
    def _canonical(value: str) -> str:
        return re.sub(r"[\W_]+", "", value).lower()

    @staticmethod
    def _remove_unconfirmed_for_documents(
        cursor,
        project_id: UUID,
        document_ids: list[UUID],
    ) -> None:
        cursor.execute(
            """
            DELETE FROM requirements
            WHERE project_id = %s
              AND status <> 'confirmed'
              AND EXISTS (
                  SELECT 1
                  FROM requirement_sources
                  JOIN source_chunks
                    ON source_chunks.id =
                       requirement_sources.source_chunk_id
                  JOIN documents
                    ON documents.id = source_chunks.document_id
                  WHERE requirement_sources.requirement_id =
                        requirements.id
                    AND documents.public_id = ANY(%s)
              )
            """,
            (project_id, document_ids),
        )

    @staticmethod
    def _select_sql() -> str:
        return """
            SELECT
                requirements.id,
                requirements.project_id,
                requirements.requirement_type AS type,
                requirements.title,
                requirements.normalized_text,
                requirements.quote,
                requirements.importance,
                requirements.confidence,
                requirements.scoring_relation,
                requirements.classification_confidence,
                requirements.classification_conflict,
                requirements.classification_notes,
                requirements.knowledge_support_required,
                requirements.status,
                requirements.proposal_relevance,
                requirements.proposal_chapter,
                requirements.target_chapter,
                requirements.need_generation,
                requirements.created_at,
                requirements.updated_at,
                source_chunks.id AS source_id,
                documents.public_id AS document_id,
                documents.filename,
                source_chunks.locator_kind,
                source_chunks.page_no,
                source_chunks.paragraph_start,
                source_chunks.paragraph_end
            FROM requirements
            JOIN requirement_sources
                ON requirement_sources.requirement_id = requirements.id
            JOIN source_chunks
                ON source_chunks.id =
                   requirement_sources.source_chunk_id
            JOIN documents
                ON documents.id = source_chunks.document_id
        """

    @staticmethod
    def _group_rows(rows) -> list[dict]:
        grouped: dict[UUID, dict] = {}
        for row in rows:
            item = grouped.setdefault(
                row["id"],
                {
                    "id": row["id"],
                    "project_id": row["project_id"],
                    "type": row["type"],
                    "title": row["title"],
                    "normalized_text": row["normalized_text"],
                    "quote": row["quote"],
                    "importance": row["importance"],
                    "confidence": float(
                        row["confidence"]
                        if isinstance(row["confidence"], Decimal)
                        else row["confidence"]
                    ),
                    "scoring_relation": row["scoring_relation"],
                    "classification_confidence": float(
                        row["classification_confidence"]
                    ),
                    "classification_conflict": row[
                        "classification_conflict"
                    ],
                    "classification_notes": row["classification_notes"],
                    "knowledge_support_required": row[
                        "knowledge_support_required"
                    ],
                    "status": row["status"],
                    "feedback": (
                        "source_mismatch"
                        if row["classification_notes"]
                        == RequirementService.SOURCE_MISMATCH_MARKER
                        else "confirmed"
                        if row["status"] == "confirmed"
                        else "not_needed"
                        if row["status"] == "rejected"
                        else "pending"
                    ),
                    "proposal_relevance": row["proposal_relevance"],
                    "proposal_chapter": row["proposal_chapter"],
                    "target_chapter": row["target_chapter"],
                    "need_generation": row["need_generation"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "sources": [],
                },
            )
            item["sources"].append(
                {
                    "id": row["source_id"],
                    "document_id": row["document_id"],
                    "filename": row["filename"],
                    "locator": {
                        "kind": row["locator_kind"],
                        "page": row["page_no"],
                        "paragraph_start": row["paragraph_start"],
                        "paragraph_end": row["paragraph_end"],
                    },
                }
            )
        return list(grouped.values())

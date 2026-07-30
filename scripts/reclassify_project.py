from __future__ import annotations

import argparse
from uuid import UUID

from app.agents.requirement_agent import AgentRequirement
from app.core.model_routing import ModelRoutingRules
from app.database.db import connect
from app.services.model_budget_service import ModelBudgetService
from app.services.requirement_service import RequirementService
from app.workflows.controlled_pipeline import ControlledPipeline


def proposal_relevance(
    importance: str,
    scoring_relation: str,
    need_generation: bool,
) -> str:
    if not need_generation:
        return "low"
    if (
        importance in {"critical", "high"}
        or scoring_relation == "high_score_item"
    ):
        return "high"
    return "medium"


def model_call_count(run_id: UUID) -> int:
    with connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*)
                FROM model_usage_events
                WHERE workflow_run_id = %s
                """,
                (run_id,),
            )
            return int(cursor.fetchone()[0])


def reclassify_project(project_id: UUID) -> dict[str, int]:
    service = RequirementService()
    stored = service.list(project_id)
    eligible = [
        item
        for item in stored
        if item["feedback"] != "source_mismatch" and item["sources"]
    ]
    if not eligible:
        return {"total": 0, "changed": 0, "model_calls": 0}

    document_ids = list(
        {
            source["document_id"]
            for item in eligible
            for source in item["sources"]
        }
    )
    project_context = service._load_project_context(  # noqa: SLF001
        project_id,
        document_ids,
    )
    rules = service.rule_engine.load("classification")
    pipeline = ControlledPipeline()
    run_id = pipeline.start(
        project_id,
        initial_stage="proposal_classification",
    )
    routing = ModelRoutingRules.load()
    ModelBudgetService.configure_limits(
        run_id,
        call_limit=routing.max_attempts,
        token_limit=120000,
    )
    before = {
        item["id"]: (
            item["type"],
            item["proposal_chapter"],
            item["importance"],
            item["scoring_relation"],
        )
        for item in eligible
    }
    agent_items = [
        AgentRequirement(
            source_id=item["sources"][0]["id"],
            title=item["title"],
            normalized_text=item["normalized_text"],
            quote=item["quote"],
            requirement_type=item["type"],
            importance=item["importance"],
            confidence=item["confidence"],
        )
        for item in eligible
    ]

    try:
        classified = service.classifier.classify(
            agent_items,
            rules,
            workflow_run_id=run_id,
            project_context=project_context,
        )
        reviewed = service.classification_reviewer.review(
            classified,
            rules,
            project_context=project_context,
        )
        checked = service.quality_pipeline.run(reviewed)
        changed = 0
        with connect() as conn:
            with conn.cursor() as cursor:
                for stored_item, result in zip(
                    eligible,
                    checked,
                    strict=True,
                ):
                    need_generation = result.proposal_chapter is not None
                    current = (
                        result.requirement_type,
                        result.proposal_chapter,
                        result.importance,
                        result.scoring_relation,
                    )
                    changed += current != before[stored_item["id"]]
                    cursor.execute(
                        """
                        UPDATE requirements
                        SET requirement_type = %s,
                            title = %s,
                            normalized_text = %s,
                            importance = %s,
                            scoring_relation = %s,
                            classification_confidence = %s,
                            classification_conflict = %s,
                            classification_notes = %s,
                            knowledge_support_required = %s,
                            proposal_relevance = %s,
                            proposal_chapter = %s,
                            target_chapter = %s,
                            need_generation = %s,
                            updated_at = NOW()
                        WHERE project_id = %s AND id = %s
                        """,
                        (
                            result.requirement_type,
                            result.item.title,
                            result.item.normalized_text,
                            result.importance,
                            result.scoring_relation,
                            result.confidence,
                            result.conflict,
                            result.rationale,
                            result.knowledge_support_required,
                            proposal_relevance(
                                result.importance,
                                result.scoring_relation,
                                need_generation,
                            ),
                            result.proposal_chapter,
                            result.proposal_chapter,
                            need_generation,
                            project_id,
                            stored_item["id"],
                        ),
                    )
        pipeline.succeed(run_id, "proposal_classification")
    except Exception as exc:
        pipeline.fail(run_id, "reclassification_failed", str(exc))
        raise

    return {
        "total": len(eligible),
        "changed": changed,
        "model_calls": model_call_count(run_id),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="原位重分类项目响应事项，保留 ID、来源和人工状态。"
    )
    parser.add_argument("project_id", type=UUID)
    args = parser.parse_args()
    print(reclassify_project(args.project_id))


if __name__ == "__main__":
    main()

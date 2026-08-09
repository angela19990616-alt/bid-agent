from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from app.core.errors import AppError
from app.knowledge.engine import (
    EnterpriseKnowledgeEngine,
    KnowledgeValidationError,
)
from app.models.configuration import (
    KnowledgeCreate,
    RuleCreate,
    RuleResponse,
)
from app.rules.engine import RuleEngine, RuleValidationError
from app.knowledge.permissions import KnowledgeAccessContext
from app.memory.historical_case_learning import (
    HistoricalCaseLearningService,
    HistoricalCasePair,
)
from app.services.document_service import extract_text


router = APIRouter(prefix="/configuration", tags=["configuration"])


def get_knowledge_engine() -> EnterpriseKnowledgeEngine:
    return EnterpriseKnowledgeEngine()


@router.get(
    "/rules/active/{rule_type}",
    response_model=RuleResponse,
)
def get_active_rule(
    rule_type: Literal[
        "extraction", "classification", "response_strategy", "knowledge",
        "proposal_memory", "writing", "compliance", "conflict_detection",
        "response_prioritization", "template_generation", "entity_relation",
    ],
):
    return RuleEngine().load(rule_type).__dict__


@router.get("/rules")
def list_rule_versions(
    rule_type: Literal[
        "extraction", "classification", "response_strategy", "knowledge",
        "proposal_memory", "writing", "compliance", "conflict_detection",
        "response_prioritization", "template_generation", "entity_relation",
    ] | None = None,
):
    return RuleEngine().list_versions(rule_type)


@router.post(
    "/rules",
    response_model=RuleResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_rule(payload: RuleCreate):
    try:
        return RuleEngine().create_version(
            payload.rule_type,
            payload.name,
            payload.content,
            source=payload.source,
            activate=payload.activate,
        ).__dict__
    except RuleValidationError as exc:
        raise AppError(422, "RULE_INVALID", str(exc)) from exc


@router.post(
    "/rules/{definition_id}/activate",
    response_model=RuleResponse,
)
def activate_rule(definition_id: UUID):
    try:
        return RuleEngine().activate(definition_id).__dict__
    except RuleValidationError as exc:
        raise AppError(404, "RULE_NOT_FOUND", str(exc)) from exc


@router.get("/knowledge")
def list_enterprise_knowledge(
    engine: EnterpriseKnowledgeEngine = Depends(get_knowledge_engine),
):
    return engine.list_summaries()


@router.post(
    "/knowledge",
    status_code=status.HTTP_201_CREATED,
)
def add_enterprise_knowledge(
    payload: KnowledgeCreate,
    engine: EnterpriseKnowledgeEngine = Depends(get_knowledge_engine),
):
    try:
        return engine.add(
            payload.category,
            payload.title,
            payload.content,
            payload.metadata,
        )
    except KnowledgeValidationError as exc:
        raise AppError(422, "KNOWLEDGE_INVALID", str(exc)) from exc


@router.post(
    "/knowledge/documents",
    status_code=status.HTTP_201_CREATED,
)
async def import_enterprise_knowledge_document(
    file: UploadFile = File(...),
    source_role: Literal[
        "response_content",
        "qualification_file",
        "standard_template",
    ] = Form("response_content"),
    engine: EnterpriseKnowledgeEngine = Depends(get_knowledge_engine),
):
    filename = file.filename or "历史投标文件"
    if not filename.lower().endswith((".pdf", ".docx")):
        raise AppError(
            415,
            "KNOWLEDGE_DOCUMENT_UNSUPPORTED",
            "历史知识文件仅支持 PDF 或 DOCX。",
        )
    try:
        return engine.import_document(
            filename,
            await file.read(),
            source_role=source_role,
        )
    except (KnowledgeValidationError, ValueError) as exc:
        raise AppError(422, "KNOWLEDGE_DOCUMENT_INVALID", str(exc)) from exc


@router.post(
    "/proposal-memory/case-pairs",
    status_code=status.HTTP_201_CREATED,
)
async def learn_historical_case_pair(
    tender_file: UploadFile = File(...),
    winning_proposal_file: UploadFile = File(...),
    project_type: str = Form(..., min_length=2, max_length=100),
    industry: str = Form(..., min_length=2, max_length=100),
    quality_score: float = Form(0.85, ge=0.7, le=1.0),
):
    tender_name = tender_file.filename or "招标文件"
    proposal_name = winning_proposal_file.filename or "中标响应文件"
    if not tender_name.lower().endswith((".pdf", ".docx")):
        raise AppError(415, "TENDER_UNSUPPORTED", "招标文件仅支持 PDF 或 DOCX。")
    if not proposal_name.lower().endswith(".docx"):
        raise AppError(
            415,
            "WINNING_PROPOSAL_UNSUPPORTED",
            "中标响应案例需提供 DOCX，才能安全提取结构模式。",
        )
    try:
        tender_content = await tender_file.read()
        proposal_content = await winning_proposal_file.read()
        pair = HistoricalCasePair(
            tender_filename=tender_name,
            tender_text=extract_text(tender_name, tender_content),
            proposal_filename=proposal_name,
            proposal_content=proposal_content,
            project_type=project_type,
            industry=industry,
            quality_score=quality_score,
        )
        learned = HistoricalCaseLearningService().learn_pairs(
            access_context=KnowledgeAccessContext.default(),
            pairs=[pair],
        )
        return {
            "learned_patterns": len(learned),
            "permission_scope": "organization_private",
            "fact_usage": "prohibited",
        }
    except (ValueError, KnowledgeValidationError) as exc:
        raise AppError(422, "CASE_PAIR_INVALID", str(exc)) from exc

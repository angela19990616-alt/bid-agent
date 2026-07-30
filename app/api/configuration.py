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


router = APIRouter(prefix="/configuration", tags=["configuration"])


def get_knowledge_engine() -> EnterpriseKnowledgeEngine:
    return EnterpriseKnowledgeEngine()


@router.get(
    "/rules/active/{rule_type}",
    response_model=RuleResponse,
)
def get_active_rule(
    rule_type: Literal[
        "extraction", "classification", "knowledge", "writing", "compliance"
    ],
):
    return RuleEngine().load(rule_type).__dict__


@router.get("/rules")
def list_rule_versions(
    rule_type: Literal[
        "extraction", "classification", "knowledge", "writing", "compliance"
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

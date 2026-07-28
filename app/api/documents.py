from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.config.settings import settings
from app.models.documents import DocumentResponse
from app.services.document_service import (
    EmptyDocumentError,
    UnsupportedDocumentError,
)
from app.services.ingestion_service import IngestionService


router = APIRouter(prefix="/documents", tags=["documents"])


@router.post(
    "/upload",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(file: UploadFile = File(...)):
    content = await file.read()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"文件不能超过 {settings.max_upload_size_mb} MB",
        )

    try:
        document_id, chunk_count = IngestionService().ingest(
            filename=file.filename or "unnamed",
            content_type=file.content_type,
            content=content,
        )
    except (UnsupportedDocumentError, EmptyDocumentError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"文档入库失败：{exc}",
        ) from exc

    return DocumentResponse(
        id=document_id,
        filename=file.filename or "unnamed",
        content_type=file.content_type,
        source_type="upload",
        chunk_count=chunk_count,
    )


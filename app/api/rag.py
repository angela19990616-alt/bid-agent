from fastapi import APIRouter, HTTPException

from app.models.documents import SearchRequest, SearchResultResponse
from app.models.generation import GenerateRequest, GenerateResponse
from app.rag.retriever import Retriever
from app.workflows.bid_workflow import graph


router = APIRouter(tags=["rag"])


def _source_response(source) -> SearchResultResponse:
    return SearchResultResponse(
        chunk_id=source.chunk_id,
        document_id=source.document_id,
        filename=source.filename,
        content=source.content,
        similarity=source.similarity,
        metadata=source.metadata,
    )


@router.post("/search", response_model=list[SearchResultResponse])
def search(request: SearchRequest):
    try:
        results = Retriever().search(request.query, request.limit)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"知识库检索失败：{exc}",
        ) from exc
    return [_source_response(result) for result in results]


@router.post("/generate", response_model=GenerateResponse)
def generate(request: GenerateRequest):
    try:
        result = graph.invoke(
            {
                "query": request.query,
                "analysis": "",
                "retrieval": "",
                "answer": "",
                "retrieval_limit": request.retrieval_limit,
                "sources": [],
            }
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"方案生成失败：{exc}",
        ) from exc

    return GenerateResponse(
        query=request.query,
        analysis=result["analysis"],
        answer=result["answer"],
        sources=[
            _source_response(source) for source in result.get("sources", [])
        ],
    )


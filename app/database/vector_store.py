from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.config.settings import settings


@dataclass(frozen=True)
class SearchResult:
    chunk_id: int
    document_id: int
    filename: str
    content: str
    similarity: float
    metadata: dict[str, Any]


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(str(value) for value in values) + "]"


class VectorStore:
    def create_document(
        self,
        filename: str,
        content_type: str | None,
        source_type: str = "upload",
    ) -> int:
        with psycopg.connect(settings.postgres_dsn) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO documents (filename, content_type, source_type)
                    VALUES (%s, %s, %s)
                    RETURNING id
                    """,
                    (filename, content_type, source_type),
                )
                return cursor.fetchone()[0]

    def add_chunks(
        self,
        document_id: int,
        chunks: list[str],
        embeddings: list[list[float]],
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("文本分块数量与向量数量不一致")

        rows = [
            (
                document_id,
                index,
                content,
                _vector_literal(embedding),
            )
            for index, (content, embedding) in enumerate(
                zip(chunks, embeddings, strict=True)
            )
        ]
        with psycopg.connect(settings.postgres_dsn) as conn:
            with conn.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO document_chunks
                        (document_id, chunk_index, content, embedding)
                    VALUES (%s, %s, %s, %s::vector)
                    """,
                    rows,
                )

    def delete_document(self, document_id: int) -> None:
        with psycopg.connect(settings.postgres_dsn) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM documents WHERE id = %s",
                    (document_id,),
                )

    def search(
        self,
        embedding: list[float],
        limit: int = 5,
    ) -> list[SearchResult]:
        vector = _vector_literal(embedding)
        with psycopg.connect(settings.postgres_dsn) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT
                        chunks.id AS chunk_id,
                        chunks.document_id,
                        documents.filename,
                        chunks.content,
                        chunks.metadata,
                        1 - (chunks.embedding <=> %s::vector) AS similarity
                    FROM document_chunks AS chunks
                    JOIN documents ON documents.id = chunks.document_id
                    WHERE chunks.embedding IS NOT NULL
                    ORDER BY chunks.embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (vector, vector, limit),
                )
                return [
                    SearchResult(
                        chunk_id=row["chunk_id"],
                        document_id=row["document_id"],
                        filename=row["filename"],
                        content=row["content"],
                        similarity=float(row["similarity"]),
                        metadata=row["metadata"] or {},
                    )
                    for row in cursor.fetchall()
                ]

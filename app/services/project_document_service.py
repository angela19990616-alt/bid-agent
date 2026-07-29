from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from psycopg.rows import dict_row

from app.agents.document_validator import (
    DocumentValidation,
    DocumentValidator,
)
from app.config.settings import settings
from app.database.db import connect
from app.services.document_service import SourceSegment, parse_document
from app.rules.engine import RuleDocument, RuleEngine


@dataclass(frozen=True)
class ProjectDocument:
    id: UUID
    project_id: UUID
    filename: str
    content_type: str | None
    size_bytes: int
    status: str
    error_code: str | None
    error_message: str | None
    source_count: int
    created_at: datetime
    updated_at: datetime
    validation_status: str = "pending"
    validation_score: float | None = None
    validation_reason: str | None = None
    knowledge_status: str = "pending"
    knowledge_scope: str = "organization_private"
    job_id: UUID | None = None


@dataclass(frozen=True)
class StoredSource:
    id: UUID
    document_id: UUID
    filename: str
    locator_kind: str
    page_no: int | None
    paragraph_start: int | None
    paragraph_end: int | None
    text: str


class ProjectDocumentNotFoundError(Exception):
    pass


class DuplicateDocumentError(Exception):
    pass


class DocumentParseFailedError(Exception):
    def __init__(
        self,
        document_id: UUID,
        job_id: UUID,
        code: str,
        message: str,
    ):
        super().__init__(message)
        self.document_id = document_id
        self.job_id = job_id
        self.code = code
        self.message = message


class ProjectDocumentService:
    def upload_and_parse(
        self,
        project_id: UUID,
        filename: str,
        content_type: str | None,
        content: bytes,
        validation_rules: RuleDocument | None = None,
    ) -> ProjectDocument:
        digest = hashlib.sha256(content).hexdigest()
        public_id = uuid4()
        job_id = uuid4()
        extension = Path(filename).suffix.lower()
        storage_key = f"{project_id}/{public_id}{extension}"
        destination = self._storage_path(storage_key)
        temporary = destination.with_suffix(destination.suffix + ".tmp")

        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            temporary.write_bytes(content)
            temporary.replace(destination)
            try:
                segments = parse_document(filename, content)
            except Exception as exc:
                code = self._parse_error_code(exc)
                self._persist_failed(
                    project_id=project_id,
                    public_id=public_id,
                    job_id=job_id,
                    filename=Path(filename).name,
                    content_type=content_type,
                    content=content,
                    digest=digest,
                    storage_key=storage_key,
                    error_code=code,
                    error_message=str(exc),
                )
                raise DocumentParseFailedError(
                    public_id,
                    job_id,
                    code,
                    str(exc),
                ) from exc
            active_rules = validation_rules or RuleEngine().load(
                "extraction"
            )
            validation = DocumentValidator().validate(
                filename, segments, active_rules
            )
            return self._persist_parsed(
                project_id=project_id,
                public_id=public_id,
                job_id=job_id,
                filename=Path(filename).name,
                content_type=content_type,
                content=content,
                digest=digest,
                storage_key=storage_key,
                segments=segments,
                validation=validation,
            )
        except DocumentParseFailedError:
            raise
        except Exception:
            temporary.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
            raise

    def list(self, project_id: UUID) -> list[ProjectDocument]:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    self._select_sql()
                    + """
                    WHERE documents.project_id = %s
                    GROUP BY documents.id
                    ORDER BY documents.updated_at DESC
                    """,
                    (project_id,),
                )
                return [
                    self._document_from_row(row)
                    for row in cursor.fetchall()
                ]

    def get(self, project_id: UUID, document_id: UUID) -> ProjectDocument:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    self._select_sql()
                    + """
                    WHERE documents.project_id = %s
                      AND documents.public_id = %s
                    GROUP BY documents.id
                    """,
                    (project_id, document_id),
                )
                row = cursor.fetchone()
        if row is None:
            raise ProjectDocumentNotFoundError(str(document_id))
        return self._document_from_row(row)

    def get_source(
        self,
        project_id: UUID,
        source_id: UUID,
    ) -> StoredSource:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT
                        source_chunks.id,
                        documents.public_id AS document_id,
                        documents.filename,
                        source_chunks.locator_kind,
                        source_chunks.page_no,
                        source_chunks.paragraph_start,
                        source_chunks.paragraph_end,
                        source_chunks.content AS text
                    FROM source_chunks
                    JOIN documents
                        ON documents.id = source_chunks.document_id
                    WHERE documents.project_id = %s
                      AND source_chunks.id = %s
                    """,
                    (project_id, source_id),
                )
                row = cursor.fetchone()
        if row is None:
            raise ProjectDocumentNotFoundError(str(source_id))
        return StoredSource(**row)

    def retry_parse(
        self,
        project_id: UUID,
        document_id: UUID,
    ) -> ProjectDocument:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id, public_id, filename, content_type, storage_key
                    FROM documents
                    WHERE project_id = %s
                      AND public_id = %s
                      AND status = 'parse_failed'
                    """,
                    (project_id, document_id),
                )
                document = cursor.fetchone()
        if document is None:
            raise ProjectDocumentNotFoundError(str(document_id))

        path = self._storage_path(document["storage_key"])
        content = path.read_bytes()
        job_id = uuid4()
        try:
            segments = parse_document(document["filename"], content)
        except Exception as exc:
            code = self._parse_error_code(exc)
            self._record_retry_failure(
                project_id,
                document["id"],
                job_id,
                code,
                str(exc),
            )
            raise DocumentParseFailedError(
                document_id,
                job_id,
                code,
                str(exc),
            ) from exc

        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    INSERT INTO processing_jobs (
                        id, project_id, job_type, status, progress,
                        input_snapshot, finished_at
                    )
                    VALUES (
                        %s, %s, 'document_parse', 'succeeded', 100,
                        '{}'::jsonb, NOW()
                    )
                    """,
                    (job_id, project_id),
                )
                cursor.execute(
                    "DELETE FROM source_chunks WHERE document_id = %s",
                    (document["id"],),
                )
                self._insert_segments(cursor, document["id"], segments)
                cursor.execute(
                    """
                    UPDATE documents
                    SET status = 'parsed',
                        error_code = NULL,
                        error_message = NULL,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (document["id"],),
                )
        result = self.get(project_id, document_id)
        return ProjectDocument(**{**result.__dict__, "job_id": job_id})

    def _persist_parsed(
        self,
        *,
        project_id: UUID,
        public_id: UUID,
        job_id: UUID,
        filename: str,
        content_type: str | None,
        content: bytes,
        digest: str,
        storage_key: str,
        segments: list[SourceSegment],
        validation: DocumentValidation,
    ) -> ProjectDocument:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    "SELECT 1 FROM projects WHERE id = %s",
                    (project_id,),
                )
                if cursor.fetchone() is None:
                    raise ProjectDocumentNotFoundError(str(project_id))
                cursor.execute(
                    """
                    SELECT public_id FROM documents
                    WHERE project_id = %s AND sha256 = %s
                    """,
                    (project_id, digest),
                )
                if cursor.fetchone() is not None:
                    raise DuplicateDocumentError(filename)
                cursor.execute(
                    """
                    SELECT 1 FROM documents
                    WHERE sha256 = %s
                      AND validation_status = 'valid'
                    LIMIT 1
                    """,
                    (digest,),
                )
                knowledge_status = (
                    "duplicate"
                    if cursor.fetchone() is not None
                    else ("eligible" if validation.is_valid else "excluded")
                )
                cursor.execute(
                    """
                    INSERT INTO processing_jobs (
                        id, project_id, job_type, status, progress,
                        input_snapshot, finished_at
                    )
                    VALUES (
                        %s, %s, 'document_parse', 'succeeded', 100,
                        %s::jsonb, NOW()
                    )
                    """,
                    (job_id, project_id, "{}"),
                )
                cursor.execute(
                    """
                    INSERT INTO documents (
                        public_id, project_id, filename, content_type,
                        source_type, sha256, size_bytes, storage_key, status
                        , validation_status, validation_score,
                        validation_reason, knowledge_status, knowledge_scope
                    )
                    VALUES (
                        %s, %s, %s, %s, 'upload', %s, %s, %s, 'parsed',
                        %s, %s, %s, %s, 'organization_private'
                    )
                    RETURNING id, created_at, updated_at
                    """,
                    (
                        public_id,
                        project_id,
                        filename,
                        content_type,
                        digest,
                        len(content),
                        storage_key,
                        "valid" if validation.is_valid else "invalid",
                        validation.score,
                        validation.reason,
                        knowledge_status,
                    ),
                )
                row = cursor.fetchone()
                document_pk = row["id"]
                self._insert_segments(cursor, document_pk, segments)
                if knowledge_status == "eligible":
                    cursor.execute(
                        """
                        INSERT INTO enterprise_knowledge (
                            category, title, content, metadata,
                            source_document_id, checksum
                        )
                        VALUES (
                            'historical_bid', %s, %s,
                            %s::jsonb, %s, %s
                        )
                        """,
                        (
                            filename,
                            "\n".join(
                                segment.text for segment in segments
                            ),
                            (
                                '{"origin":"validated_tender",'
                                '"usage":"private_rag_only",'
                                '"public_training":false}'
                            ),
                            document_pk,
                            digest,
                        ),
                    )
                cursor.execute(
                    """
                    UPDATE projects
                    SET status = 'reviewing_requirements', updated_at = NOW()
                    WHERE id = %s
                    """,
                    (project_id,),
                )
        return ProjectDocument(
            id=public_id,
            project_id=project_id,
            filename=filename,
            content_type=content_type,
            size_bytes=len(content),
            status="parsed",
            error_code=None,
            error_message=None,
            source_count=len(segments),
            validation_status=(
                "valid" if validation.is_valid else "invalid"
            ),
            validation_score=validation.score,
            validation_reason=validation.reason,
            knowledge_status=knowledge_status,
            knowledge_scope="organization_private",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            job_id=job_id,
        )

    def _persist_failed(
        self,
        *,
        project_id: UUID,
        public_id: UUID,
        job_id: UUID,
        filename: str,
        content_type: str | None,
        content: bytes,
        digest: str,
        storage_key: str,
        error_code: str,
        error_message: str,
    ) -> None:
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM projects WHERE id = %s",
                    (project_id,),
                )
                if cursor.fetchone() is None:
                    raise ProjectDocumentNotFoundError(str(project_id))
                cursor.execute(
                    """
                    SELECT 1 FROM documents
                    WHERE project_id = %s AND sha256 = %s
                    """,
                    (project_id, digest),
                )
                if cursor.fetchone() is not None:
                    raise DuplicateDocumentError(filename)
                cursor.execute(
                    """
                    INSERT INTO processing_jobs (
                        id, project_id, job_type, status, progress,
                        input_snapshot, error_code, error_message, finished_at
                    )
                    VALUES (
                        %s, %s, 'document_parse', 'failed', 0,
                        '{}'::jsonb, %s, %s, NOW()
                    )
                    """,
                    (job_id, project_id, error_code, error_message),
                )
                cursor.execute(
                    """
                    INSERT INTO documents (
                        public_id, project_id, filename, content_type,
                        source_type, sha256, size_bytes, storage_key, status,
                        error_code, error_message
                    )
                    VALUES (
                        %s, %s, %s, %s, 'upload', %s, %s, %s,
                        'parse_failed', %s, %s
                    )
                    """,
                    (
                        public_id,
                        project_id,
                        filename,
                        content_type,
                        digest,
                        len(content),
                        storage_key,
                        error_code,
                        error_message,
                    ),
                )

    def _record_retry_failure(
        self,
        project_id: UUID,
        document_pk: int,
        job_id: UUID,
        error_code: str,
        error_message: str,
    ) -> None:
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO processing_jobs (
                        id, project_id, job_type, status, progress,
                        input_snapshot, error_code, error_message, finished_at
                    )
                    VALUES (
                        %s, %s, 'document_parse', 'failed', 0,
                        '{}'::jsonb, %s, %s, NOW()
                    )
                    """,
                    (job_id, project_id, error_code, error_message),
                )
                cursor.execute(
                    """
                    UPDATE documents
                    SET error_code = %s, error_message = %s, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (error_code, error_message, document_pk),
                )

    @staticmethod
    def _select_sql() -> str:
        return """
            SELECT
                documents.public_id AS id,
                documents.project_id,
                documents.filename,
                documents.content_type,
                documents.size_bytes,
                documents.status,
                documents.error_code,
                documents.error_message,
                documents.validation_status,
                documents.validation_score,
                documents.validation_reason,
                documents.knowledge_status,
                documents.knowledge_scope,
                COUNT(source_chunks.id) AS source_count,
                documents.created_at,
                documents.updated_at
            FROM documents
            LEFT JOIN source_chunks
                ON source_chunks.document_id = documents.id
        """

    @staticmethod
    def _document_from_row(row) -> ProjectDocument:
        return ProjectDocument(**row)

    @staticmethod
    def _storage_path(storage_key: str) -> Path:
        root = Path(settings.storage_root).resolve()
        destination = (root / storage_key).resolve()
        if root not in destination.parents:
            raise ValueError("非法存储路径")
        return destination

    @staticmethod
    def _parse_error_code(exc: Exception) -> str:
        name = type(exc).__name__
        return {
            "EmptyDocumentError": "DOCUMENT_EMPTY",
            "EncryptedDocumentError": "DOCUMENT_ENCRYPTED",
            "UnsupportedDocumentError": "DOCUMENT_UNSUPPORTED",
        }.get(name, "DOCUMENT_PARSE_FAILED")

    @staticmethod
    def _insert_segments(cursor, document_pk: int, segments) -> None:
        cursor.executemany(
            """
            INSERT INTO source_chunks (
                document_id, chunk_index, locator_kind, page_no,
                paragraph_start, paragraph_end, content
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    document_pk,
                    index,
                    segment.locator_kind,
                    segment.page_no,
                    segment.paragraph_start,
                    segment.paragraph_end,
                    segment.text,
                )
                for index, segment in enumerate(segments)
            ],
        )

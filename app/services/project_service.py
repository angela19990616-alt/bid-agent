from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from psycopg.rows import dict_row

from app.database.db import connect


@dataclass(frozen=True)
class Project:
    id: UUID
    name: str
    status: str
    created_at: datetime
    updated_at: datetime
    document_count: int = 0
    requirement_count: int = 0
    section_count: int = 0


class ProjectNotFoundError(Exception):
    pass


class ProjectService:
    def create(self, name: str) -> Project:
        clean_name = name.strip()
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    INSERT INTO projects (name)
                    VALUES (%s)
                    RETURNING id, name, status, created_at, updated_at
                    """,
                    (clean_name,),
                )
                return Project(**cursor.fetchone())

    def list(self) -> list[Project]:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id, name, status, created_at, updated_at
                    FROM projects
                    ORDER BY updated_at DESC, id
                    """
                )
                return [Project(**row) for row in cursor.fetchall()]

    def get(self, project_id: UUID) -> Project:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT
                        projects.id,
                        projects.name,
                        projects.status,
                        projects.created_at,
                        projects.updated_at,
                        COUNT(DISTINCT documents.id) AS document_count,
                        COUNT(DISTINCT requirements.id) AS requirement_count,
                        COUNT(DISTINCT sections.id) AS section_count
                    FROM projects
                    LEFT JOIN documents
                        ON documents.project_id = projects.id
                    LEFT JOIN requirements
                        ON requirements.project_id = projects.id
                    LEFT JOIN sections
                        ON sections.project_id = projects.id
                    WHERE projects.id = %s
                    GROUP BY projects.id
                    """,
                    (project_id,),
                )
                row = cursor.fetchone()
        if row is None:
            raise ProjectNotFoundError(str(project_id))
        return Project(**row)

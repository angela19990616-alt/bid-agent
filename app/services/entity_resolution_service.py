from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row

from app.core.entity_resolution import (
    EntityCandidate,
    EntityResolutionContext,
    Organization,
    Person,
    ProjectRole,
    ProjectRoleAssignment,
)
from app.database.db import connect


class EntityResolutionService:
    """Load only verified, organization-private entities for one project."""

    def resolve_project(self, project_id: UUID) -> EntityResolutionContext:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT p.id, p.name, p.organization_key,
                           o.id AS organization_id, o.full_name,
                           o.unified_social_credit_code,
                           o.registered_address,
                           o.legal_representative_person_id,
                           o.source_location, o.confidence
                    FROM projects p
                    LEFT JOIN enterprise_organizations o
                      ON o.id = p.bidder_organization_id
                     AND o.organization_key = p.organization_key
                     AND o.permission_scope = 'organization_private'
                     AND o.verification_status = 'verified'
                    WHERE p.id = %s
                    """,
                    (project_id,),
                )
                project = cursor.fetchone()
                if project is None:
                    raise ValueError("项目不存在，无法解析实体关系。")
                organization = self._organization(project)
                people = self._people(cursor, project, organization)
                assignments = self._assignments(
                    cursor, project_id, organization
                )
        candidates = self._candidates(people, organization)
        return EntityResolutionContext(
            project_id=project_id,
            project_name=str(project["name"] or "") or None,
            organization=organization,
            people=tuple(people),
            assignments=tuple(assignments),
            candidates_by_role=candidates,
        )

    def bind_role(
        self,
        project_id: UUID,
        *,
        role: ProjectRole,
        person_id: UUID,
    ) -> None:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT p.bidder_organization_id, p.organization_key,
                           ep.id AS person_id
                    FROM projects p
                    LEFT JOIN enterprise_people ep
                      ON ep.id = %s
                     AND ep.organization_id = p.bidder_organization_id
                     AND ep.organization_key = p.organization_key
                     AND ep.permission_scope = 'organization_private'
                     AND ep.verification_status = 'verified'
                    WHERE p.id = %s
                    FOR UPDATE OF p
                    """,
                    (person_id, project_id),
                )
                row = cursor.fetchone()
                if row is None:
                    raise ValueError("项目不存在。")
                organization_id = row["bidder_organization_id"]
                if organization_id is None:
                    raise ValueError("当前项目尚未绑定投标主体。")
                if row["person_id"] is None:
                    raise ValueError(
                        "所选人员不属于当前投标主体或尚未完成资料核验。"
                    )
                cursor.execute(
                    """
                    UPDATE project_role_assignments
                    SET status = 'revoked', updated_at = NOW()
                    WHERE project_id = %s AND role = %s
                      AND status = 'active'
                    """,
                    (project_id, role.value),
                )
                cursor.execute(
                    """
                    INSERT INTO project_role_assignments (
                        project_id, organization_id, role, person_id,
                        status, source_document, source_location,
                        confidence
                    )
                    VALUES (
                        %s, %s, %s, %s, 'active',
                        '当前项目人工审核',
                        '{"location":"角色绑定审核"}'::jsonb,
                        1
                    )
                    """,
                    (project_id, organization_id, role.value, person_id),
                )
                if role is ProjectRole.LEGAL_REPRESENTATIVE:
                    cursor.execute(
                        """
                        UPDATE enterprise_organizations
                        SET legal_representative_person_id = %s,
                            updated_at = NOW()
                        WHERE id = %s
                        """,
                        (person_id, organization_id),
                    )

    @staticmethod
    def _organization(row: dict[str, Any]) -> Organization | None:
        if row.get("organization_id") is None:
            return None
        location = row.get("source_location") or {}
        return Organization(
            id=row["organization_id"],
            full_name=str(row["full_name"]),
            unified_social_credit_code=row.get(
                "unified_social_credit_code"
            ),
            registered_address=row.get("registered_address"),
            legal_representative_person_id=row.get(
                "legal_representative_person_id"
            ),
            source_document=location.get("document"),
            source_location=location.get("location"),
            confidence=float(row.get("confidence") or 0),
        )

    @staticmethod
    def _people(cursor, project, organization) -> list[Person]:
        if organization is None:
            return []
        cursor.execute(
            """
            SELECT id, name, title, phone_masked, id_number_masked,
                   certificates, source_documents
            FROM enterprise_people
            WHERE organization_key = %s
              AND organization_id = %s
              AND permission_scope = 'organization_private'
              AND verification_status = 'verified'
            ORDER BY name
            """,
            (project["organization_key"], organization.id),
        )
        return [
            Person(
                id=row["id"],
                name=str(row["name"]),
                title=row.get("title"),
                phone_masked=row.get("phone_masked"),
                id_number_masked=row.get("id_number_masked"),
                certificates=tuple(row.get("certificates") or ()),
                source_documents=tuple(row.get("source_documents") or ()),
            )
            for row in cursor.fetchall()
        ]

    @staticmethod
    def _assignments(
        cursor,
        project_id: UUID,
        organization: Organization | None,
    ) -> list[ProjectRoleAssignment]:
        if organization is None:
            return []
        cursor.execute(
            """
            SELECT project_id, role, person_id, organization_id,
                   authorization_document_id, valid_from, valid_to,
                   status, source_document, source_location, confidence
            FROM project_role_assignments
            WHERE project_id = %s
              AND organization_id = %s
              AND status = 'active'
              AND (valid_from IS NULL OR valid_from <= CURRENT_DATE)
              AND (valid_to IS NULL OR valid_to >= CURRENT_DATE)
            ORDER BY role
            """,
            (project_id, organization.id),
        )
        return [
            ProjectRoleAssignment(
                project_id=row["project_id"],
                role=ProjectRole(row["role"]),
                person_id=row["person_id"],
                organization_id=row["organization_id"],
                authorization_document_id=row.get(
                    "authorization_document_id"
                ),
                valid_from=EntityResolutionService._date(
                    row.get("valid_from")
                ),
                valid_to=EntityResolutionService._date(
                    row.get("valid_to")
                ),
                status=str(row["status"]),
                source_document=row.get("source_document"),
                source_location=(
                    (row.get("source_location") or {}).get("location")
                ),
                confidence=float(row.get("confidence") or 0),
            )
            for row in cursor.fetchall()
        ]

    @staticmethod
    def _date(value: Any) -> date | None:
        return value if isinstance(value, date) else None

    @staticmethod
    def _candidates(
        people: list[Person],
        organization: Organization | None,
    ) -> dict[ProjectRole, tuple[EntityCandidate, ...]]:
        if organization is None:
            return {}
        items = tuple(
            EntityCandidate(
                person_id=person.id,
                name=person.name,
                title=person.title,
                match_basis="同一投标主体的已核验人员，尚需建立项目角色绑定",
                source_document=(
                    str(person.source_documents[0].get("title"))
                    if person.source_documents
                    and isinstance(person.source_documents[0], dict)
                    and person.source_documents[0].get("title")
                    else None
                ),
                source_location=(
                    str(person.source_documents[0].get("location"))
                    if person.source_documents
                    and isinstance(person.source_documents[0], dict)
                    and person.source_documents[0].get("location")
                    else None
                ),
                confidence=1.0,
            )
            for person in people
        )
        return {role: items for role in ProjectRole}

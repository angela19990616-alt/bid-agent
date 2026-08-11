from __future__ import annotations

import json
from datetime import date
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row

from app.core.entity_resolution import (
    EntityCandidate,
    EntityResolutionContext,
    Organization,
    OrganizationCandidate,
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
                organization_candidates = self._organization_candidates(
                    cursor, project
                )
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
            organization_candidates=tuple(organization_candidates),
        )

    def bind_organization(
        self,
        project_id: UUID,
        *,
        organization_id: UUID,
    ) -> None:
        """Bind one verified organization without guessing from its name."""
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT p.bidder_organization_id, o.id AS candidate_id
                    FROM projects p
                    LEFT JOIN enterprise_organizations o
                      ON o.id = %s
                     AND o.organization_key = p.organization_key
                     AND o.permission_scope = 'organization_private'
                     AND o.verification_status = 'verified'
                    WHERE p.id = %s
                    FOR UPDATE OF p
                    """,
                    (organization_id, project_id),
                )
                row = cursor.fetchone()
                if row is None:
                    raise ValueError("项目不存在。")
                if row["candidate_id"] is None:
                    raise ValueError(
                        "所选企业不属于当前机构或尚未完成资料核验。"
                    )
                if row["bidder_organization_id"] == organization_id:
                    return
                self._clear_entity_reviews(
                    cursor,
                    project_id,
                    entity_types={"Organization", "Person"},
                )
                cursor.execute(
                    """
                    UPDATE project_role_assignments
                    SET status = 'revoked', updated_at = NOW()
                    WHERE project_id = %s AND status = 'active'
                    """,
                    (project_id,),
                )
                cursor.execute(
                    """
                    UPDATE projects
                    SET bidder_organization_id = %s, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (organization_id, project_id),
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
                self._clear_entity_reviews(
                    cursor,
                    project_id,
                    entity_types={"Person"},
                    roles={role.value},
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
    def _organization_candidates(
        cursor,
        project: dict[str, Any],
    ) -> list[OrganizationCandidate]:
        cursor.execute(
            """
            SELECT o.id, o.full_name, o.source_location, o.confidence,
                   d.filename AS source_document
            FROM enterprise_organizations o
            LEFT JOIN documents d ON d.id = o.source_document_id
            WHERE o.organization_key = %s
              AND o.permission_scope = 'organization_private'
              AND o.verification_status = 'verified'
            ORDER BY o.full_name
            """,
            (project["organization_key"],),
        )
        return [
            OrganizationCandidate(
                organization_id=row["id"],
                name=str(row["full_name"]),
                match_basis="同一机构企业库中的已核验投标主体候选",
                source_document=row.get("source_document"),
                source_location=(
                    (row.get("source_location") or {}).get("location")
                ),
                confidence=float(row.get("confidence") or 0),
            )
            for row in cursor.fetchall()
        ]

    @staticmethod
    def _entity_field_keys(
        descriptor: dict[str, Any],
        *,
        entity_types: set[str],
        roles: set[str] | None = None,
    ) -> set[str]:
        return {
            str(field.get("field_key"))
            for field in descriptor.get("fields") or ()
            if field.get("field_key")
            and str(field.get("expected_entity_type") or "") in entity_types
            and (
                roles is None
                or str(field.get("expected_role") or "") in roles
            )
        }

    @classmethod
    def _clear_entity_reviews(
        cls,
        cursor,
        project_id: UUID,
        *,
        entity_types: set[str],
        roles: set[str] | None = None,
    ) -> None:
        """Prevent a newly selected entity from inheriting old confirmed data."""
        cursor.execute(
            """
            SELECT template_descriptor, template_field_values,
                   last_fill_report
            FROM proposal_generation_profiles
            WHERE project_id = %s
            FOR UPDATE
            """,
            (project_id,),
        )
        profile = cursor.fetchone()
        if profile is None:
            return
        field_keys = cls._entity_field_keys(
            profile.get("template_descriptor") or {},
            entity_types=entity_types,
            roles=roles,
        )
        values = dict(profile.get("template_field_values") or {})
        report = dict(profile.get("last_fill_report") or {})
        field_reviews = dict(report.get("field_reviews") or {})
        for field_key in field_keys:
            values.pop(field_key, None)
            field_reviews.pop(field_key, None)
        report["field_reviews"] = field_reviews
        # Variable reviews are an audit summary only. Rebuild them from the
        # still-valid field reviews instead of risking a stale entity label.
        report["variable_reviews"] = {}
        cursor.execute(
            """
            UPDATE proposal_generation_profiles
            SET template_field_values = %s::jsonb,
                last_fill_report = %s::jsonb,
                updated_at = NOW()
            WHERE project_id = %s
            """,
            (
                json.dumps(values, ensure_ascii=False),
                json.dumps(report, ensure_ascii=False),
                project_id,
            ),
        )

    @staticmethod
    def _people(cursor, project, organization) -> list[Person]:
        if organization is None:
            return []
        cursor.execute(
            """
            SELECT id, name, title, phone_masked, id_number_masked,
                   certificates, source_documents, employment_history,
                   role_history, certification_history,
                   project_participation
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
                employment_history=tuple(
                    row.get("employment_history") or ()
                ),
                role_history=tuple(row.get("role_history") or ()),
                certification_history=tuple(
                    row.get("certification_history") or ()
                ),
                project_participation=tuple(
                    row.get("project_participation") or ()
                ),
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

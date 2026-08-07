from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row

from app.config.settings import settings
from app.database.db import connect
from app.services.response_template_service import ResponseTemplateService


@dataclass(frozen=True)
class GenerationProfile:
    project_id: UUID
    generation_mode: str
    historical_case_mode: str
    template_descriptor: dict[str, Any]
    template_field_values: dict[str, str]
    template_storage_key: str | None = None
    template_filename: str | None = None


class GenerationProfileService:
    def __init__(self, template_service: ResponseTemplateService | None = None):
        self.template_service = template_service or ResponseTemplateService()

    def inspect_document(
        self,
        *,
        project_id: UUID,
        document_id: UUID,
        filename: str,
        content: bytes,
    ) -> GenerationProfile:
        descriptor = self.template_service.detect(filename, content)
        source_fields = self.template_service.extract_source_fields(
            filename, content
        )
        mode = self.mode_for_descriptor(descriptor.snapshot())
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id, storage_key FROM documents
                    WHERE project_id = %s AND public_id = %s
                    """,
                    (project_id, document_id),
                )
                document = cursor.fetchone()
                if document is None:
                    raise ValueError("模板来源文件不存在。")
                cursor.execute(
                    """
                    INSERT INTO proposal_generation_profiles (
                        project_id, generation_mode, template_document_id,
                        template_descriptor, template_field_values
                    )
                    VALUES (%s, %s, %s, %s::jsonb, %s::jsonb)
                    ON CONFLICT (project_id) DO UPDATE SET
                        generation_mode = CASE
                            WHEN EXCLUDED.generation_mode = 'strict_template'
                                THEN EXCLUDED.generation_mode
                            WHEN proposal_generation_profiles.generation_mode =
                                'strict_template'
                                THEN proposal_generation_profiles.generation_mode
                            WHEN EXCLUDED.generation_mode =
                                'pdf_template_manual_fill'
                                THEN EXCLUDED.generation_mode
                            WHEN proposal_generation_profiles.generation_mode =
                                'pdf_template_manual_fill'
                                THEN proposal_generation_profiles.generation_mode
                            ELSE EXCLUDED.generation_mode
                        END,
                        template_document_id = CASE
                            WHEN EXCLUDED.generation_mode = 'strict_template'
                                THEN EXCLUDED.template_document_id
                            WHEN proposal_generation_profiles.generation_mode =
                                'strict_template'
                                THEN proposal_generation_profiles.template_document_id
                            WHEN EXCLUDED.generation_mode =
                                'pdf_template_manual_fill'
                                THEN EXCLUDED.template_document_id
                            WHEN proposal_generation_profiles.generation_mode =
                                'pdf_template_manual_fill'
                                THEN proposal_generation_profiles.template_document_id
                            ELSE EXCLUDED.template_document_id
                        END,
                        template_descriptor = CASE
                            WHEN EXCLUDED.generation_mode = 'strict_template'
                                THEN EXCLUDED.template_descriptor
                            WHEN proposal_generation_profiles.generation_mode =
                                'strict_template'
                                THEN proposal_generation_profiles.template_descriptor
                            WHEN EXCLUDED.generation_mode =
                                'pdf_template_manual_fill'
                                THEN EXCLUDED.template_descriptor
                            WHEN proposal_generation_profiles.generation_mode =
                                'pdf_template_manual_fill'
                                THEN proposal_generation_profiles.template_descriptor
                            ELSE EXCLUDED.template_descriptor
                        END,
                        template_field_values = CASE
                            WHEN EXCLUDED.generation_mode = 'strict_template'
                                THEN EXCLUDED.template_field_values ||
                                     proposal_generation_profiles.template_field_values
                            ELSE proposal_generation_profiles.template_field_values
                        END,
                        updated_at = NOW()
                    """,
                    (
                        project_id,
                        mode,
                        document["id"] if descriptor.detected else None,
                        json.dumps(descriptor.snapshot(), ensure_ascii=False),
                        json.dumps(source_fields, ensure_ascii=False),
                    ),
                )
        return self.get(project_id)

    @staticmethod
    def mode_for_descriptor(descriptor: dict[str, Any]) -> str:
        if descriptor.get("detected") and descriptor.get("source_format") == "docx":
            return "strict_template"
        if descriptor.get("detected") and descriptor.get("source_format") == "pdf":
            return "pdf_template_manual_fill"
        return "planned"

    @staticmethod
    def preferred_mode(existing: str, incoming: str) -> str:
        priority = {
            "planned": 1,
            "pdf_template_manual_fill": 2,
            "strict_template": 3,
        }
        return (
            incoming
            if priority.get(incoming, 0) >= priority.get(existing, 0)
            else existing
        )

    @staticmethod
    def get(project_id: UUID) -> GenerationProfile:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT p.project_id, p.generation_mode,
                           p.historical_case_mode, p.template_descriptor,
                           p.template_field_values,
                           d.storage_key AS template_storage_key,
                           d.filename AS template_filename
                    FROM proposal_generation_profiles p
                    LEFT JOIN documents d ON d.id = p.template_document_id
                    WHERE p.project_id = %s
                    """,
                    (project_id,),
                )
                row = cursor.fetchone()
        if row is None:
            return GenerationProfile(
                project_id=project_id,
                generation_mode="planned",
                historical_case_mode="closest_case",
                template_descriptor={},
                template_field_values={},
            )
        return GenerationProfile(**row)

    @staticmethod
    def update_template_fields(
        project_id: UUID,
        values: dict[str, str],
    ) -> GenerationProfile:
        cleaned: dict[str, str] = {}
        for raw_key, raw_value in values.items():
            key = str(raw_key).strip()
            value = str(raw_value).strip()
            if not key or len(key) > 80 or not value or len(value) > 500:
                raise ValueError("模板字段名或字段值无效。")
            cleaned[key] = value
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE proposal_generation_profiles
                    SET template_field_values = %s::jsonb,
                        updated_at = NOW()
                    WHERE project_id = %s
                    """,
                    (json.dumps(cleaned, ensure_ascii=False), project_id),
                )
                if cursor.rowcount == 0:
                    raise ValueError("方案生成档案不存在。")
        return GenerationProfileService.get(project_id)

    @staticmethod
    def template_path(profile: GenerationProfile) -> Path | None:
        if not profile.template_storage_key:
            return None
        root = Path(settings.storage_root).resolve()
        path = (root / profile.template_storage_key).resolve()
        if root not in path.parents:
            raise ValueError("非法模板存储路径。")
        return path

    @staticmethod
    def record_fill_report(project_id: UUID, report: dict[str, Any]) -> None:
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE proposal_generation_profiles
                    SET last_fill_report = %s::jsonb, updated_at = NOW()
                    WHERE project_id = %s
                    """,
                    (json.dumps(report, ensure_ascii=False), project_id),
                )

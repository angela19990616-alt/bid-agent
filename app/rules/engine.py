from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row

from app.config.settings import settings
from app.database.db import connect


RULE_TYPES = {
    "extraction", "classification", "response_strategy", "knowledge",
    "proposal_memory", "writing", "compliance",
    "conflict_detection", "response_prioritization",
}


class RuleValidationError(ValueError):
    pass


@dataclass(frozen=True)
class RuleDocument:
    rule_type: str
    rule_key: str
    name: str
    version: int
    content: dict[str, Any]
    checksum: str
    source: str
    definition_id: UUID | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "definition_id": (
                str(self.definition_id) if self.definition_id else None
            ),
            "rule_type": self.rule_type,
            "rule_key": self.rule_key,
            "name": self.name,
            "version": self.version,
            "checksum": self.checksum,
            "source": self.source,
        }


class RuleEngine:
    FILES = {
        "extraction": "extraction.default.json",
        "classification": "classification.default.json",
        "response_strategy": "response_strategy.default.json",
        "conflict_detection": "conflict_detection.default.json",
        "response_prioritization": "response_prioritization.default.json",
        "knowledge": "knowledge.default.json",
        "proposal_memory": "proposal_memory.default.json",
        "writing": "writing.default.json",
        "compliance": "compliance.default.json",
    }

    def load(self, rule_type: str) -> RuleDocument:
        if rule_type not in RULE_TYPES:
            raise RuleValidationError(f"未知规则类型：{rule_type}")
        database_rule = self._load_active(rule_type)
        return database_rule or self._load_default(rule_type)

    def load_default(self, rule_type: str) -> RuleDocument:
        if rule_type not in RULE_TYPES:
            raise RuleValidationError(f"未知规则类型：{rule_type}")
        return self._load_default(rule_type)

    def create_version(
        self,
        rule_type: str,
        name: str,
        content: dict[str, Any],
        *,
        source: str = "manual",
        activate: bool = False,
    ) -> RuleDocument:
        self._validate(rule_type, content)
        canonical = json.dumps(
            content, ensure_ascii=False, sort_keys=True
        )
        checksum = hashlib.sha256(canonical.encode()).hexdigest()
        rule_key = str(content.get("key") or f"default-{rule_type}")
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT COALESCE(MAX(version), 0) + 1 AS next_version
                    FROM rule_definitions
                    WHERE organization_key = 'default'
                      AND rule_type = %s AND rule_key = %s
                    """,
                    (rule_type, rule_key),
                )
                version = cursor.fetchone()["next_version"]
                if activate:
                    cursor.execute(
                        """
                        UPDATE rule_definitions
                        SET status = 'retired'
                        WHERE organization_key = 'default'
                          AND rule_type = %s AND status = 'active'
                        """,
                        (rule_type,),
                    )
                cursor.execute(
                    """
                    INSERT INTO rule_definitions (
                        rule_type, rule_key, name, version, status,
                        source, content, checksum, activated_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s::jsonb, %s,
                        CASE WHEN %s THEN NOW() ELSE NULL END
                    )
                    RETURNING id
                    """,
                    (
                        rule_type,
                        rule_key,
                        name.strip(),
                        version,
                        "active" if activate else "draft",
                        source,
                        canonical,
                        checksum,
                        activate,
                    ),
                )
                definition_id = cursor.fetchone()["id"]
        return RuleDocument(
            rule_type, rule_key, name.strip(), version, content,
            checksum, source, definition_id
        )

    def list_versions(self, rule_type: str | None = None) -> list[dict]:
        where = ""
        params: tuple = ()
        if rule_type:
            where = "WHERE rule_type = %s"
            params = (rule_type,)
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    f"""
                    SELECT id, rule_type, rule_key, name, version, status,
                           source, checksum, content, created_at, activated_at
                    FROM rule_definitions
                    {where}
                    ORDER BY rule_type, version DESC
                    """,
                    params,
                )
                return [dict(row) for row in cursor.fetchall()]

    def activate(self, definition_id: UUID) -> RuleDocument:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT * FROM rule_definitions WHERE id = %s
                    FOR UPDATE
                    """,
                    (definition_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise RuleValidationError("规则版本不存在。")
                cursor.execute(
                    """
                    UPDATE rule_definitions SET status = 'retired'
                    WHERE organization_key = %s AND rule_type = %s
                      AND status = 'active'
                    """,
                    (row["organization_key"], row["rule_type"]),
                )
                cursor.execute(
                    """
                    UPDATE rule_definitions
                    SET status = 'active', activated_at = NOW()
                    WHERE id = %s
                    """,
                    (definition_id,),
                )
        return self.load(row["rule_type"])

    def _load_active(self, rule_type: str) -> RuleDocument | None:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id, rule_type, rule_key, name, version, content,
                           checksum, source
                    FROM rule_definitions
                    WHERE organization_key = 'default'
                      AND rule_type = %s AND status = 'active'
                    """,
                    (rule_type,),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        content = dict(row["content"])
        self._validate(rule_type, content)
        return RuleDocument(
            row["rule_type"], row["rule_key"], row["name"],
            row["version"], content, row["checksum"], row["source"],
            row["id"]
        )

    def _load_default(self, rule_type: str) -> RuleDocument:
        path = Path(settings.rules_root) / self.FILES[rule_type]
        content = json.loads(path.read_text(encoding="utf-8"))
        self._validate(rule_type, content)
        canonical = json.dumps(
            content, ensure_ascii=False, sort_keys=True
        )
        return RuleDocument(
            rule_type=rule_type,
            rule_key=str(content["key"]),
            name=str(content["name"]),
            version=int(content["version"]),
            content=content,
            checksum=hashlib.sha256(canonical.encode()).hexdigest(),
            source="system",
        )

    @staticmethod
    def _validate(rule_type: str, content: dict[str, Any]) -> None:
        if content.get("rule_type") != rule_type:
            raise RuleValidationError("规则类型与内容不一致。")
        for field in ("key", "name", "version"):
            if not content.get(field):
                raise RuleValidationError(f"规则缺少字段：{field}")
        if rule_type == "extraction":
            required = (
                "document_validation", "candidate_markers", "types",
                "proposal_mapping",
                "proposal_routing_defaults",
                "model_instruction", "output_schema"
            )
        elif rule_type == "classification":
            required = (
                "requirement_types", "classifiers", "chapter_mapping",
                "scoring_keywords", "importance_keywords",
                "model_instruction", "output_schema"
            )
        elif rule_type == "response_strategy":
            required = (
                "actions", "hard_rules", "type_defaults",
                "manual_proposal_chapters", "priority_policy"
            )
        elif rule_type == "conflict_detection":
            required = (
                "difference_types", "source_authority", "topic_keywords",
                "conflict_priority", "confidence_thresholds",
            )
        elif rule_type == "response_prioritization":
            required = ("proposal_value", "hard_rules", "p0_evidence_keywords")
        elif rule_type == "knowledge":
            required = ("eligibility", "matching", "fact_boundaries")
        elif rule_type == "proposal_memory":
            required = ("eligibility", "usage", "fact_boundary")
        elif rule_type == "writing":
            required = (
                "chapter_order", "policies", "chapter_styles",
                "knowledge_category_policy", "model_instruction",
                "user_template"
            )
        else:
            required = ("checks", "required_traceability")
        missing = [field for field in required if field not in content]
        if missing:
            raise RuleValidationError(
                "规则缺少必要配置：" + "、".join(missing)
            )

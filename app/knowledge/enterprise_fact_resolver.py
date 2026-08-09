from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.rows import dict_row

from app.core.strict_fill import DataSensitivity, EnterpriseFact
from app.database.db import connect


class EnterpriseFactResolver:
    """Resolve structured, verified facts from the private knowledge store.

    Historical bids are deliberately ignored: they can influence structure and
    writing style, but can never become company facts for strict filling.
    """

    ALLOWED_CATEGORIES = {"company_profile", "qualification"}

    def resolve(self, project_id: UUID) -> list[EnterpriseFact]:
        # Fetch only compact structured metadata. Loading historical bid bodies
        # here would add avoidable latency to every workspace status poll.
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT k.category, k.title, k.metadata
                    FROM enterprise_knowledge k
                    JOIN projects p
                      ON p.organization_key = k.organization_key
                    WHERE p.id = %s
                      AND k.status = 'active'
                      AND k.permission_scope = 'organization_private'
                      AND k.category = ANY(%s)
                      AND k.metadata->>'verified_enterprise_fact' = 'true'
                    ORDER BY k.updated_at DESC
                    """,
                    (project_id, sorted(self.ALLOWED_CATEGORIES)),
                )
                entries = [dict(row) for row in cursor.fetchall()]
        facts: list[EnterpriseFact] = []
        for item in entries:
            metadata = item.get("metadata") or {}
            for canonical_key, payload in self._items(metadata):
                fact = self._fact(item, canonical_key, payload)
                if fact is not None:
                    facts.append(fact)
        return facts

    @staticmethod
    def _items(metadata: dict[str, Any]):
        structured = metadata.get("enterprise_facts")
        if isinstance(structured, dict):
            yield from structured.items()
        key = metadata.get("canonical_key")
        if isinstance(key, str) and key.strip() and "value" in metadata:
            yield key, metadata.get("value")

    @staticmethod
    def _fact(
        item: dict[str, Any],
        canonical_key: str,
        payload: Any,
    ) -> EnterpriseFact | None:
        details = payload if isinstance(payload, dict) else {"value": payload}
        value = str(details.get("value") or "").strip()
        if not canonical_key.strip() or not value:
            return None
        sensitivity_value = str(details.get("sensitivity") or "normal")
        try:
            sensitivity = DataSensitivity(sensitivity_value)
        except ValueError:
            sensitivity = DataSensitivity.SENSITIVE
        return EnterpriseFact(
            canonical_key=canonical_key.strip(),
            value=value,
            source_type=str(item.get("category") or "company_profile"),
            source_reference=str(
                details.get("source_reference") or item.get("title") or "企业知识库"
            ),
            confidence=float(details.get("confidence", 1.0)),
            verified=details.get("verified", True) is True,
            sensitivity=sensitivity,
            evidence_title=str(
                details.get("evidence_title")
                or details.get("source_reference")
                or item.get("title")
                or "企业知识库"
            ),
            evidence_excerpt=(
                str(details.get("evidence_excerpt")).strip()
                if details.get("evidence_excerpt")
                else None
            ),
            evidence_location=(
                str(details.get("evidence_location")).strip()
                if details.get("evidence_location")
                else None
            ),
        )

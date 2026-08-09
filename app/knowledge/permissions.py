from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class KnowledgeAccessContext:
    organization_key: str
    workspace_id: UUID | None = None
    user_id: str | None = None
    allowed_scopes: tuple[str, ...] = ("organization_private",)

    @classmethod
    def default(cls) -> "KnowledgeAccessContext":
        return cls(organization_key="default")


class KnowledgePermissionFilter:
    """Fail-closed authorization applied before knowledge matching."""

    def __init__(self, context: KnowledgeAccessContext):
        if not context.organization_key.strip():
            raise ValueError("机构权限上下文不能为空。")
        if not context.allowed_scopes:
            raise ValueError("知识权限范围不能为空。")
        self.context = context

    def allows(self, item: dict) -> bool:
        return (
            item.get("organization_key")
            == self.context.organization_key
            and item.get("permission_scope")
            in self.context.allowed_scopes
        )

    @property
    def sql_params(self) -> tuple[str, list[str]]:
        return (
            self.context.organization_key,
            list(self.context.allowed_scopes),
        )

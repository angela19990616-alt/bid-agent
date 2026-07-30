from uuid import uuid4

import pytest

from app.knowledge.permissions import (
    KnowledgeAccessContext,
    KnowledgePermissionFilter,
)


def test_permission_filter_allows_only_same_organization_and_scope():
    permission = KnowledgePermissionFilter(
        KnowledgeAccessContext(
            organization_key="enterprise-a",
            workspace_id=uuid4(),
        )
    )

    assert permission.allows(
        {
            "organization_key": "enterprise-a",
            "permission_scope": "organization_private",
        }
    )
    assert not permission.allows(
        {
            "organization_key": "enterprise-b",
            "permission_scope": "organization_private",
        }
    )
    assert not permission.allows(
        {
            "organization_key": "enterprise-a",
            "permission_scope": "public",
        }
    )


def test_permission_context_fails_closed_without_scope_or_organization():
    with pytest.raises(ValueError):
        KnowledgePermissionFilter(
            KnowledgeAccessContext(
                organization_key="",
            )
        )
    with pytest.raises(ValueError):
        KnowledgePermissionFilter(
            KnowledgeAccessContext(
                organization_key="enterprise-a",
                allowed_scopes=(),
            )
        )

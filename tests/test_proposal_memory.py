import pytest

from app.knowledge.permissions import KnowledgeAccessContext
from app.memory.engine import (
    ProposalMemoryEngine,
    ProposalMemoryValidationError,
)


def test_memory_pattern_must_prohibit_fact_copy():
    with pytest.raises(ProposalMemoryValidationError):
        ProposalMemoryEngine().add_pattern(
            access_context=KnowledgeAccessContext("enterprise-a"),
            project_type="咨询服务",
            industry="文旅",
            chapter_title="实施方案",
            pattern={"sections": ["工作分解", "进度安排"]},
            quality_score=0.9,
        )


def test_memory_terms_support_structure_matching():
    query = ProposalMemoryEngine._terms("智慧文旅实施计划")
    pattern = ProposalMemoryEngine._terms(
        "实施计划 工作分解 进度安排 质量控制"
    )

    assert query & pattern

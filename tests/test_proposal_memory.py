import pytest
from uuid import uuid4

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


def test_memory_match_deduplicates_generic_chapters_per_source(monkeypatch):
    source_pair = "case-pair-a"
    rows = [
        {
            "id": uuid4(),
            "organization_key": "enterprise-a",
            "project_type": "投融资咨询服务",
            "industry": "工业园区投融资",
            "chapter_title": "通用响应章节",
            "pattern": {
                "source_pair_checksum": source_pair,
                "chapter_structure": ["通用响应章节"],
            },
            "permission_scope": "organization_private",
            "quality_score": 0.9,
        },
        {
            "id": uuid4(),
            "organization_key": "enterprise-a",
            "project_type": "投融资咨询服务",
            "industry": "工业园区投融资",
            "chapter_title": "通用响应章节",
            "pattern": {
                "source_pair_checksum": source_pair,
                "chapter_structure": ["通用响应章节"],
            },
            "permission_scope": "organization_private",
            "quality_score": 0.9,
        },
    ]

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, *_args):
            return None

        def fetchall(self):
            return rows

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def cursor(self, **_kwargs):
            return Cursor()

    monkeypatch.setattr("app.memory.engine.connect", Connection)
    matches = ProposalMemoryEngine().match(
        access_context=KnowledgeAccessContext("enterprise-a"),
        section_title="工业园区投融资方案",
        requirements=[],
        limit=3,
    )

    assert len(matches) == 1
    assert matches[0].pattern["source_pair_checksum"] == source_pair

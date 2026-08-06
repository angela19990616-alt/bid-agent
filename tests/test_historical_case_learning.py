import json
from io import BytesIO
from uuid import uuid4

from docx import Document

from app.knowledge.permissions import KnowledgeAccessContext
from app.memory.historical_case_learning import (
    HistoricalCaseLearningService,
    HistoricalCasePair,
    HistoricalCasePatternExtractor,
)


def _winning_bid() -> bytes:
    document = Document()
    document.add_heading("第一章 项目理解", level=1)
    document.add_paragraph("甲公司为某市客户建设了金额500万元的智慧平台。")
    document.add_heading("1.1 总体思路", level=2)
    document.add_paragraph("采用分层方法展开论证，并给出闭环措施。")
    table = document.add_table(rows=2, cols=3)
    table.cell(0, 0).text = "阶段"
    table.cell(0, 1).text = "时间"
    table.cell(0, 2).text = "成果"
    table.cell(1, 0).text = "历史阶段A"
    table.cell(1, 1).text = "30天"
    table.cell(1, 2).text = "旧项目成果"
    stream = BytesIO()
    document.save(stream)
    return stream.getvalue()


def test_case_learning_keeps_structure_but_removes_historical_facts():
    patterns = HistoricalCasePatternExtractor().extract(_winning_bid())
    snapshot = json.dumps(patterns, ensure_ascii=False)

    assert patterns
    assert patterns[0]["prohibited_fact_copy"] is True
    assert patterns[0]["source_facts_removed"] is True
    assert "项目理解" in snapshot
    assert "阶段" in snapshot and "时间" in snapshot and "成果" in snapshot
    assert "甲公司" not in snapshot
    assert "某市客户" not in snapshot
    assert "500万元" not in snapshot
    assert "历史阶段A" not in snapshot


def test_case_pair_learning_preserves_private_organization_boundary():
    calls = []

    class FakeMemoryEngine:
        def add_pattern(self, **kwargs):
            calls.append(kwargs)
            return uuid4()

    context = KnowledgeAccessContext("enterprise-a")
    learned = HistoricalCaseLearningService(
        memory_engine=FakeMemoryEngine()
    ).learn_pairs(
        access_context=context,
        pairs=[
            HistoricalCasePair(
                tender_filename="tender.docx",
                tender_text="智慧文旅项目采购需求",
                proposal_filename="winning.docx",
                proposal_content=_winning_bid(),
                project_type="咨询服务",
                industry="文旅",
            )
        ],
    )

    assert learned
    assert calls
    assert all(item["access_context"] is context for item in calls)
    assert all(
        item["pattern"]["reference_scope"] == "organization_private"
        for item in calls
    )
    snapshot = json.dumps(
        [item["pattern"] for item in calls], ensure_ascii=False
    )
    assert "甲公司" not in snapshot
    assert "500万元" not in snapshot

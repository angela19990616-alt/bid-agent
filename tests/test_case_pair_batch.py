import json
from io import BytesIO

import pytest
from docx import Document

from app.knowledge.permissions import KnowledgeAccessContext
from app.memory.case_pair_batch import (
    CasePairBatchImporter,
    CasePairManifestError,
)


def _docx_bytes(*paragraphs: str) -> bytes:
    document = Document()
    for value in paragraphs:
        document.add_paragraph(value)
    stream = BytesIO()
    document.save(stream)
    return stream.getvalue()


def _write_manifest(tmp_path, count: int = 5):
    pairs = []
    for index in range(1, count + 1):
        directory = tmp_path / f"case-{index:02d}"
        directory.mkdir()
        (directory / "tender.docx").write_bytes(
            _docx_bytes("采购需求", f"第{index}组实施服务要求")
        )
        (directory / "winning.docx").write_bytes(
            _docx_bytes(
                "第一章 项目理解",
                f"旧客户{index}金额{index * 100}万元，禁止进入新项目。",
                "1.1 总体思路",
                "采用分层论证和闭环控制。",
            )
        )
        pairs.append(
            {
                "tender": f"case-{index:02d}/tender.docx",
                "winning_proposal": f"case-{index:02d}/winning.docx",
                "project_type": "咨询服务",
                "industry": "文旅",
                "quality_score": 0.85,
            }
        )
    manifest = tmp_path / "pairs.json"
    manifest.write_text(
        json.dumps({"pairs": pairs}, ensure_ascii=False),
        encoding="utf-8",
    )
    return manifest


def test_five_pair_manifest_dry_run_validates_without_database_write(tmp_path):
    class NoWriteLearningService:
        def learn_pairs(self, **kwargs):
            raise AssertionError("dry-run 不应写入数据库")

    report = CasePairBatchImporter(
        learning_service=NoWriteLearningService()
    ).run(
        _write_manifest(tmp_path),
        access_context=KnowledgeAccessContext("enterprise-a"),
        dry_run=True,
    )

    assert report.pair_count == 5
    assert report.pattern_count >= 5
    assert report.learned_pattern_count == 0
    assert report.permission_scope == "organization_private"
    assert report.fact_usage == "prohibited"


def test_incomplete_batch_is_rejected_before_any_database_write(tmp_path):
    calls = []

    class FakeLearningService:
        def learn_pairs(self, **kwargs):
            calls.append(kwargs)
            return []

    with pytest.raises(CasePairManifestError, match="恰好包含 5 组"):
        CasePairBatchImporter(
            learning_service=FakeLearningService()
        ).run(
            _write_manifest(tmp_path, count=4),
            access_context=KnowledgeAccessContext("enterprise-a"),
        )

    assert calls == []


def test_manifest_cannot_read_case_files_outside_its_directory(tmp_path):
    outside = tmp_path.parent / "outside.docx"
    outside.write_bytes(_docx_bytes("采购需求"))
    manifest = _write_manifest(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["pairs"][0]["tender"] = "../outside.docx"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CasePairManifestError, match="必须位于清单目录内"):
        CasePairBatchImporter().load_manifest(manifest)

from datetime import UTC, datetime
from uuid import uuid4

from app.models.exports import ExportResponse
from app.rules.engine import RuleEngine
from app.services.section_service import SectionService


class _FakePipeline:
    def latest(self, project_id):
        return uuid4()

    def record(self, *args, **kwargs):
        return None


class _FileRuleEngine:
    def load(self, rule_type):
        return RuleEngine().load_default(rule_type)


class _FakeCursor:
    def __init__(self, current_version_id):
        self.current_version_id = current_version_id
        self.executed = []
        self._result = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        self.executed.append(normalized)
        if "SELECT sections.current_version_id" in normalized:
            self._result = {
                "current_version_id": self.current_version_id,
                "rule_snapshot": {},
                "knowledge_snapshot": [],
            }
        elif "COALESCE(MAX(version_no), 0) + 1" in normalized:
            self._result = {"next_version": 2}
        elif "INSERT INTO section_versions" in normalized:
            self._result = {"id": uuid4()}
        else:
            self._result = None

    def fetchone(self):
        return self._result

    def executemany(self, query, rows):
        self.executed.append(" ".join(query.split()))


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def cursor(self, **kwargs):
        return self._cursor


def test_full_export_response_allows_no_single_section():
    item = ExportResponse(
        id=uuid4(),
        project_id=uuid4(),
        section_id=None,
        section_version_id=None,
        export_scope="full_proposal",
        format="docx",
        status="succeeded",
        filename="技术方案.docx",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    assert item.export_scope == "full_proposal"
    assert item.section_id is None


def test_section_save_locks_only_sections_table(monkeypatch):
    project_id = uuid4()
    section_id = uuid4()
    version_id = uuid4()
    cursor = _FakeCursor(version_id)
    monkeypatch.setattr(
        "app.services.section_service.connect",
        lambda: _FakeConnection(cursor),
    )
    monkeypatch.setattr(
        "app.services.section_service.ControlledPipeline",
        _FakePipeline,
    )
    monkeypatch.setattr(
        SectionService,
        "get",
        lambda self, project_id, section_id: {
            "id": section_id,
            "status": "edited",
        },
    )

    result = SectionService(rule_engine=_FileRuleEngine()).save_content(
        project_id,
        section_id,
        version_id,
        "有证据支持的人工修订正文。",
    )

    select_query = next(
        query
        for query in cursor.executed
        if "SELECT sections.current_version_id" in query
    )
    assert "WHERE sections.project_id =" in select_query
    assert "AND sections.id =" in select_query
    assert "FOR UPDATE OF sections" in select_query
    assert result["status"] == "edited"

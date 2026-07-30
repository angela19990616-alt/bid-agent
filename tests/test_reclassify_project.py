from uuid import uuid4

import scripts.reclassify_project as reclassify_module
from scripts.reclassify_project import (
    model_call_count,
    proposal_relevance,
    reconcile_draft_outline,
)


def test_reclassification_keeps_compliance_out_of_proposal():
    assert proposal_relevance("critical", "high_score_item", False) == "low"


def test_reclassification_prioritizes_important_proposal_items():
    assert proposal_relevance("high", "requirement_only", True) == "high"
    assert proposal_relevance("medium", "high_score_item", True) == "high"
    assert proposal_relevance("medium", "requirement_only", True) == "medium"


def test_model_call_count_uses_current_workflow(monkeypatch):
    run_id = uuid4()
    executed = {}

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, sql, params):
            executed["sql"] = sql
            executed["params"] = params

        def fetchone(self):
            return (3,)

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def cursor(self):
            return Cursor()

    monkeypatch.setattr(reclassify_module, "connect", Connection)

    assert model_call_count(run_id) == 3
    assert executed["params"] == (run_id,)
    assert "model_usage_events" in executed["sql"]


def test_outline_reconciliation_is_bounded_to_drafts():
    class Cursor:
        def __init__(self):
            self.calls = []
            self.rowcount = 1

        def execute(self, sql, params):
            self.calls.append((sql, params))

    cursor = Cursor()
    project_id = uuid4()

    assert reconcile_draft_outline(cursor, project_id) == 5
    assert len(cursor.calls) == 5
    assert all(call[1][-1] == project_id for call in cursor.calls)
    assert all(
        "current_version_id IS NULL" in call[0]
        for call in (cursor.calls[0], cursor.calls[1], cursor.calls[4])
    )

from datetime import timedelta
from uuid import uuid4

from app.services.workspace_job_service import (
    AUTONOMOUS_DRAFT_JOB,
    SECTION_GENERATION_JOB,
    WorkspaceJobService,
)


class Cursor:
    def __init__(self, row=None, rowcount=0):
        self.row = row
        self.rowcount = rowcount
        self.executed = []

    def execute(self, sql, params):
        self.executed.append((sql, params))

    def fetchone(self):
        return self.row

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class Connection:
    def __init__(self, cursor):
        self.value = cursor

    def cursor(self, **_kwargs):
        return self.value

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


def test_enqueue_persists_only_job_references(monkeypatch):
    cursor = Cursor()
    monkeypatch.setattr(
        "app.services.workspace_job_service.connect",
        lambda: Connection(cursor),
    )
    workspace_id = uuid4()
    document_id = uuid4()
    run_id = uuid4()

    job_id = WorkspaceJobService().enqueue(
        workspace_id, document_id, run_id
    )

    assert job_id
    sql, params = cursor.executed[0]
    assert "status, progress" in sql
    assert params[1] == workspace_id
    assert str(document_id) in params[3]
    assert str(run_id) in params[3]


def test_claim_uses_skip_locked_for_single_worker_job(monkeypatch):
    workspace_id = uuid4()
    document_id = uuid4()
    run_id = uuid4()
    cursor = Cursor(
        {
            "id": uuid4(),
            "project_id": workspace_id,
            "job_type": "workspace_pipeline",
            "input_snapshot": {
                "document_id": str(document_id),
                "workflow_run_id": str(run_id),
            },
        }
    )
    monkeypatch.setattr(
        "app.services.workspace_job_service.connect",
        lambda: Connection(cursor),
    )

    job = WorkspaceJobService().claim_next()

    assert job is not None
    assert job.workspace_id == workspace_id
    assert job.document_id == document_id
    assert "FOR UPDATE SKIP LOCKED" in cursor.executed[0][0]


def test_autonomous_draft_enqueue_is_idempotent(monkeypatch):
    workspace_id = uuid4()
    existing_job = uuid4()
    cursor = Cursor({"id": existing_job})
    monkeypatch.setattr(
        "app.services.workspace_job_service.connect",
        lambda: Connection(cursor),
    )

    job_id = WorkspaceJobService().enqueue_autonomous_draft(workspace_id)

    assert job_id == existing_job
    assert cursor.executed[0][1] == (workspace_id, AUTONOMOUS_DRAFT_JOB)
    assert len(cursor.executed) == 1


def test_section_generation_enqueue_persists_bounded_request(monkeypatch):
    workspace_id = uuid4()
    section_id = uuid4()
    cursor = Cursor(None)
    monkeypatch.setattr(
        "app.services.workspace_job_service.connect",
        lambda: Connection(cursor),
    )

    job_id = WorkspaceJobService().enqueue_section_generation(
        workspace_id,
        section_id,
        instruction="突出进度控制",
        case_reference_mode="closest_case",
        min_chars=800,
        max_chars=5000,
    )

    assert job_id
    assert cursor.executed[0][1] == (workspace_id, SECTION_GENERATION_JOB)
    sql, params = cursor.executed[1]
    assert "'queued'" in sql
    assert str(section_id) in params[3]
    assert "突出进度控制" in params[3]


def test_recover_stale_only_requeues_workspace_jobs(monkeypatch):
    cursor = Cursor(rowcount=2)
    monkeypatch.setattr(
        "app.services.workspace_job_service.connect",
        lambda: Connection(cursor),
    )

    recovered = WorkspaceJobService().recover_stale(
        after=timedelta(minutes=20)
    )

    assert recovered == 2
    sql, params = cursor.executed[0]
    assert "status = 'running'" in sql
    assert params[1] == timedelta(minutes=20)

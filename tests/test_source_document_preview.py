from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.workspaces import authorize_workspace
from app.main import app
from app.services.project_document_service import ProjectDocumentService


def teardown_function():
    app.dependency_overrides.clear()


def test_source_document_preview_returns_original_file_inline(
    monkeypatch,
    tmp_path,
):
    source = tmp_path / "采购文件.docx"
    source.write_bytes(b"original-procurement-document")
    workspace_id = uuid4()
    document_id = uuid4()
    app.dependency_overrides[authorize_workspace] = lambda: None
    monkeypatch.setattr(
        ProjectDocumentService,
        "source_file",
        lambda _service, project_id, requested_document_id: (
            source,
            "采购文件.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        if (project_id, requested_document_id) == (workspace_id, document_id)
        else None,
    )

    response = TestClient(app).get(
        f"/api/v1/workspaces/{workspace_id}/documents/{document_id}/source"
    )

    assert response.status_code == 200
    assert response.content == b"original-procurement-document"
    assert response.headers["cache-control"] == "no-store, private"
    assert response.headers["content-disposition"].startswith("inline;")


import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "acceptance_mvp.py"
SPEC = importlib.util.spec_from_file_location("acceptance_mvp", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_acceptance_report_omits_source_and_generated_text():
    workspace = {
        "id": "W1",
        "status": "outline_ready",
        "document": {"validation_status": "valid"},
        "technical_requirements": [
            {
                "type": "scoring",
                "target_chapter": "技术评分点响应",
                "sources": [{"locator": {"page": 8}}],
            }
        ],
        "compliance_reminder_count": 2,
        "outline": [
            {
                "id": "S1",
                "title": "技术评分点响应",
                "requirement_ids": ["R1"],
            }
        ],
    }

    summary = MODULE.summarize_workspace(workspace)

    assert summary["technical_requirement_count"] == 1
    assert summary["traceable_requirement_count"] == 1
    assert "sources" not in summary
    assert "content" not in summary


def test_generated_section_summary_only_exposes_counts():
    section = {
        "id": "S1",
        "title": "实施计划",
        "status": "generated",
        "current_version": {"content": "私密生成正文"},
        "findings": [
            {"severity": "blocking", "message": "私密校核详情"}
        ],
    }

    summary = MODULE.summarize_section(section)

    assert summary["content_chars"] == 6
    assert summary["blocking"] is True
    assert "content" not in summary
    assert "message" not in summary


def test_acceptance_waits_for_async_workspace_before_generation():
    class FakeClient:
        timeout = 1

        def __init__(self):
            self.reads = 0

        def workspace(self, workspace_id):
            self.reads += 1
            return {
                "id": workspace_id,
                "status": "outline_ready",
                "outline": [],
            }

    client = FakeClient()
    result = MODULE.AcceptanceClient.wait_until_ready(
        client,
        {"id": "W1", "status": "extracting"},
        poll_interval=0,
    )

    assert result["status"] == "outline_ready"
    assert client.reads == 1


def test_acceptance_client_reuses_cookie_capable_opener():
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps({"status": "outline_ready"}).encode()

    class Opener:
        def open(self, request, timeout):
            calls.append((request.full_url, timeout))
            return Response()

    client = MODULE.AcceptanceClient(
        "http://127.0.0.1", timeout=12, opener=Opener()
    )

    assert client.workspace("workspace-1")["status"] == "outline_ready"
    assert calls == [
        ("http://127.0.0.1/api/v1/workspaces/workspace-1", 12)
    ]


def test_acceptance_invite_uses_same_cookie_opener_without_logging_code():
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b'{"authorized": true}'

    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            return Response()

    client = MODULE.AcceptanceClient(
        "http://127.0.0.1", opener=Opener()
    )
    result = client.authorize_invite("private-code")

    assert result == {"authorized": True}
    assert requests[0].full_url.endswith("/api/v1/access/invite")
    assert json.loads(requests[0].data) == {"code": "private-code"}

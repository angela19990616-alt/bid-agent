#!/usr/bin/env python3
"""Run a privacy-safe real-document acceptance against a Bid Agent API."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


def build_multipart(path: Path) -> tuple[bytes, str]:
    boundary = f"bid-agent-{uuid4().hex}"
    content_type = (
        mimetypes.guess_type(path.name)[0]
        or "application/octet-stream"
    )
    prefix = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; '
        f'filename="{path.name}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode()
    body = prefix + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def summarize_workspace(workspace: dict) -> dict:
    requirements = workspace.get("technical_requirements", [])
    by_type: dict[str, int] = {}
    by_chapter: dict[str, int] = {}
    traceable = 0
    for item in requirements:
        requirement_type = str(item.get("type") or "unknown")
        target = str(item.get("target_chapter") or "未映射")
        by_type[requirement_type] = by_type.get(requirement_type, 0) + 1
        by_chapter[target] = by_chapter.get(target, 0) + 1
        if item.get("sources"):
            traceable += 1
    return {
        "workspace_id": workspace.get("id"),
        "status": workspace.get("status"),
        "document_validation": (
            workspace.get("document") or {}
        ).get("validation_status"),
        "technical_requirement_count": len(requirements),
        "traceable_requirement_count": traceable,
        "requirements_by_type": by_type,
        "requirements_by_target_chapter": by_chapter,
        "compliance_reminder_count": workspace.get(
            "compliance_reminder_count", 0
        ),
        "outline": [
            {
                "section_id": item.get("id"),
                "title": item.get("title"),
                "requirement_count": len(item.get("requirement_ids", [])),
            }
            for item in workspace.get("outline", [])
        ],
    }


def summarize_section(section: dict) -> dict:
    version = section.get("current_version") or {}
    findings = section.get("findings", [])
    severity_counts: dict[str, int] = {}
    for item in findings:
        severity = str(item.get("severity") or "unknown")
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
    return {
        "section_id": section.get("id"),
        "title": section.get("title"),
        "status": section.get("status"),
        "content_chars": len(version.get("content") or ""),
        "finding_counts": severity_counts,
        "blocking": severity_counts.get("blocking", 0) > 0,
    }


class AcceptanceClient:
    def __init__(
        self,
        base_url: str,
        timeout: int = 300,
        opener=None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.opener = opener or urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar())
        )

    def upload(self, path: Path) -> dict:
        body, content_type = build_multipart(path)
        request = urllib.request.Request(
            f"{self.base_url}/api/v1/workspaces",
            data=body,
            method="POST",
            headers={"Content-Type": content_type},
        )
        return self._json(request)

    def authorize_invite(self, code: str) -> dict:
        request = urllib.request.Request(
            f"{self.base_url}/api/v1/access/invite",
            data=json.dumps({"code": code}).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        return self._json(request)

    def generate(self, workspace_id: str, section_id: str) -> dict:
        request = urllib.request.Request(
            f"{self.base_url}/api/v1/workspaces/{workspace_id}"
            f"/sections/{section_id}/generate",
            data=b"",
            method="POST",
        )
        return self._json(request)

    def workspace(self, workspace_id: str) -> dict:
        request = urllib.request.Request(
            f"{self.base_url}/api/v1/workspaces/{workspace_id}",
            method="GET",
        )
        return self._json(request)

    def wait_until_ready(
        self,
        workspace: dict,
        *,
        poll_interval: float = 2.0,
    ) -> dict:
        workspace_id = str(workspace["id"])
        deadline = time.monotonic() + self.timeout
        current = workspace
        while current.get("status") not in {
            "outline_ready",
            "draft",
        }:
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"workspace {workspace_id} processing timed out"
                )
            time.sleep(poll_interval)
            current = self.workspace(workspace_id)
        if current.get("status") != "outline_ready":
            raise RuntimeError(
                f"workspace {workspace_id} processing failed"
            )
        return current

    def _json(self, request: urllib.request.Request) -> dict:
        with self.opener.open(
            request, timeout=self.timeout
        ) as response:
            return json.load(response)


def run(path: Path, client: AcceptanceClient) -> dict:
    workspace = client.wait_until_ready(client.upload(path))
    summary = summarize_workspace(workspace)
    generated = []
    for section in workspace.get("outline", []):
        result = client.generate(workspace["id"], section["id"])
        generated.append(summarize_section(result))
    blocking = sum(1 for item in generated if item["blocking"])
    return {
        "schema_version": 1,
        "started_at": datetime.now(UTC).isoformat(),
        "input": {
            "size_bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "extension": path.suffix.lower(),
        },
        "workspace": summary,
        "generation": generated,
        "gates": {
            "all_requirements_traceable": (
                summary["technical_requirement_count"]
                == summary["traceable_requirement_count"]
            ),
            "has_technical_requirements": (
                summary["technical_requirement_count"] > 0
            ),
            "has_outline": bool(summary["outline"]),
            "blocking_section_count": blocking,
            "ready_for_human_edit": bool(generated),
            "ready_for_approval": bool(generated) and blocking == 0,
        },
        "privacy": {
            "contains_source_text": False,
            "contains_generated_content": False,
            "contains_model_credentials": False,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bid Agent 真实文件隐私安全验收"
    )
    parser.add_argument("file", type=Path)
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=900,
        help="单次上传或章节生成超时秒数，默认 900",
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.file.is_file() or args.file.suffix.lower() not in {
        ".pdf",
        ".docx",
    }:
        print("验收文件必须是存在的 PDF 或 DOCX。", file=sys.stderr)
        return 2
    try:
        client = AcceptanceClient(args.base_url, timeout=args.timeout)
        invite_code = os.getenv("BID_AGENT_INVITE_CODE", "").strip()
        if invite_code:
            client.authorize_invite(invite_code)
        report = run(
            args.file,
            client,
        )
    except urllib.error.HTTPError as exc:
        error_code = f"HTTP_{exc.code}"
        try:
            payload = json.loads(exc.read().decode())
            error_code = payload.get("error", {}).get("code", error_code)
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        print(f"验收失败：{error_code}", file=sys.stderr)
        return 1
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if report["gates"]["ready_for_human_edit"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import logging
import signal
import time

from app.services.workspace_job_service import WorkspaceJobService
from app.services.workspace_service import WorkspaceService
from app.services.autonomous_draft_service import AutonomousDraftService
from app.services.section_service import SectionService
from app.services.workspace_job_service import (
    AUTONOMOUS_DRAFT_JOB,
    SECTION_GENERATION_JOB,
)


LOGGER = logging.getLogger("bid-agent.workspace-worker")
POLL_SECONDS = 1.0
_running = True


def _stop(_signum, _frame) -> None:
    global _running
    _running = False


def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    jobs = WorkspaceJobService()
    recovered = jobs.recover_stale()
    if recovered:
        LOGGER.warning("Recovered %s stale workspace job(s)", recovered)
    LOGGER.info("Workspace worker started")
    last_recovery_check = time.monotonic()
    while _running:
        if time.monotonic() - last_recovery_check >= 60:
            recovered = jobs.recover_stale()
            if recovered:
                LOGGER.warning("Recovered %s stale workspace job(s)", recovered)
            last_recovery_check = time.monotonic()
        job = jobs.claim_next()
        if job is None:
            time.sleep(POLL_SECONDS)
            continue
        LOGGER.info("Processing workspace job %s", job.id)
        try:
            if job.job_type == AUTONOMOUS_DRAFT_JOB:
                AutonomousDraftService().run(job.workspace_id, job.id)
            elif job.job_type == SECTION_GENERATION_JOB:
                if job.section_id is None:
                    raise ValueError("章节生成任务缺少章节引用。")
                SectionService().generate(
                    job.workspace_id,
                    job.section_id,
                    job.input_snapshot.get("instruction"),
                    job.input_snapshot.get("case_reference_mode", "balanced"),
                    int(job.input_snapshot.get("min_chars", 800)),
                    int(job.input_snapshot.get("max_chars", 5000)),
                )
            else:
                if job.document_id is None or job.workflow_run_id is None:
                    raise ValueError("文档处理任务缺少必要引用。")
                WorkspaceService().complete_prepared_upload(
                    job.workspace_id,
                    job.document_id,
                    job.workflow_run_id,
                )
        except Exception as exc:
            jobs.fail(job.id, exc)
            LOGGER.exception("Workspace job %s failed", job.id)
        else:
            jobs.succeed(job.id)
            LOGGER.info("Workspace job %s succeeded", job.id)
    LOGGER.info("Workspace worker stopped")


if __name__ == "__main__":
    run()

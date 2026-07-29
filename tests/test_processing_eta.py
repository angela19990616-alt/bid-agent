from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.services.processing_eta_service import ProcessingEtaService


def test_eta_uses_completed_local_workloads_and_current_source_count(
    monkeypatch,
):
    monkeypatch.setattr(
        ProcessingEtaService,
        "_samples",
        lambda workspace_id: [(300.0, 100), (600.0, 200)],
    )

    estimate = ProcessingEtaService.estimate(
        uuid4(),
        status="extracting",
        created_at=datetime.now(timezone.utc) - timedelta(seconds=60),
        source_count=150,
    )

    assert estimate.basis == "historical_completed_workloads"
    assert estimate.sample_count == 2
    assert 0 < estimate.remaining_seconds_low
    assert (
        estimate.remaining_seconds_low
        <= estimate.remaining_seconds_high
    )


def test_eta_does_not_invent_duration_without_history(monkeypatch):
    monkeypatch.setattr(
        ProcessingEtaService,
        "_samples",
        lambda workspace_id: [],
    )

    estimate = ProcessingEtaService.estimate(
        uuid4(),
        status="extracting",
        created_at=datetime.now(timezone.utc),
        source_count=120,
    )

    assert estimate.remaining_seconds_low is None
    assert estimate.remaining_seconds_high is None
    assert estimate.basis == "insufficient_history"


def test_completed_workspace_has_zero_remaining_time(monkeypatch):
    estimate = ProcessingEtaService.estimate(
        uuid4(),
        status="outline_ready",
        created_at=datetime.now(timezone.utc),
        source_count=120,
    )

    assert estimate.remaining_seconds_low == 0
    assert estimate.remaining_seconds_high == 0

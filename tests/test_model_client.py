from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.config.settings import settings
from app.core.model_client import ModelClient
from app.services.model_budget_service import (
    ModelBudgetExceeded,
    ModelBudgetService,
    ModelReservation,
)


class FakeCompletions:
    def __init__(self, output_text: str):
        self.output_text = output_text
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self.output_text)
                )
            ]
        )


class FakeOpenAI:
    def __init__(self, output_text: str):
        self.chat = SimpleNamespace(
            completions=FakeCompletions(output_text)
        )


def test_chat_uses_openai_compatible_chat_completions_api():
    client = FakeOpenAI("生成结果")

    result = ModelClient(client=client).chat(
        [{"role": "user", "content": "生成本章"}],
        temperature=0.1,
        max_tokens=1234,
    )

    assert result == "生成结果"
    assert client.chat.completions.calls == [
        {
            "model": settings.llm_model,
            "messages": [{"role": "user", "content": "生成本章"}],
            "temperature": 0.1,
            "max_tokens": 1234,
        }
    ]


def test_chat_rejects_empty_model_output():
    with pytest.raises(RuntimeError, match="模型返回了空内容"):
        ModelClient(client=FakeOpenAI("")).chat(
            [{"role": "user", "content": "生成本章"}]
        )


@pytest.mark.parametrize(
    ("task", "expected"),
    [
        ("extraction", settings.extraction_model),
        ("classification", settings.classification_model),
        ("writing", settings.writing_model),
        ("review", settings.review_model),
        ("unknown", settings.llm_model),
    ],
)
def test_chat_routes_model_by_bounded_task(task, expected):
    client = FakeOpenAI("完成")
    ModelClient(client=client).chat(
        [{"role": "user", "content": "测试"}],
        task=task,
    )
    assert client.chat.completions.calls[0]["model"] == expected


def test_budget_is_reserved_and_finished_around_model_call(monkeypatch):
    events = []
    monkeypatch.setattr(
        ModelBudgetService,
        "reserve",
        lambda run_id, **kwargs: (
            events.append(("reserve", run_id, kwargs))
            or ModelReservation(7, kwargs["estimated_tokens"])
        ),
    )
    monkeypatch.setattr(
        ModelBudgetService,
        "finish",
        lambda reservation, **kwargs: events.append(
            ("finish", reservation.event_id, kwargs)
        ),
    )
    run_id = uuid4()

    result = ModelClient(client=FakeOpenAI("完成")).chat(
        [{"role": "user", "content": "生成本章"}],
        task="writing",
        max_tokens=100,
        workflow_run_id=run_id,
    )

    assert result == "完成"
    assert events[0][0:2] == ("reserve", run_id)
    assert events[0][2]["model"] == settings.writing_model
    assert events[1] == (
        "finish",
        7,
        {"actual_tokens": None},
    )


def test_budget_limit_stops_before_model_call(monkeypatch):
    client = FakeOpenAI("不应调用")

    def reject(*_args, **_kwargs):
        raise ModelBudgetExceeded("预算已用完")

    monkeypatch.setattr(ModelBudgetService, "reserve", reject)
    with pytest.raises(ModelBudgetExceeded, match="预算已用完"):
        ModelClient(client=client).chat(
            [{"role": "user", "content": "生成"}],
            workflow_run_id=uuid4(),
        )
    assert client.chat.completions.calls == []


def test_token_estimate_includes_maximum_output_budget():
    estimate = ModelBudgetService.estimate(
        [{"role": "user", "content": "测试内容"}],
        max_tokens=5000,
    )
    assert estimate > 5000


def test_20k_character_tender_gets_large_but_bounded_budget():
    calls, tokens = ModelBudgetService.limits_for_text(20000)

    assert calls >= 36
    assert tokens == 240000
    assert calls <= settings.max_model_calls_per_workflow
    assert tokens <= settings.max_model_tokens_per_workflow


def test_chapter_budget_is_smaller_than_workflow_hard_cap(monkeypatch):
    captured = {}

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _query, params):
            captured["params"] = params

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def cursor(self):
            return Cursor()

    monkeypatch.setattr(
        "app.services.model_budget_service.connect",
        lambda: Connection(),
    )
    run_id = uuid4()

    limits = ModelBudgetService.configure_limits(
        run_id,
        call_limit=2,
        token_limit=80000,
    )

    assert limits == {
        "model_call_limit": 2,
        "model_token_limit": 80000,
    }
    assert captured["params"] == (2, 80000, run_id)

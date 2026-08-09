from types import SimpleNamespace
from uuid import uuid4

import pytest

import app.core.model_client as model_client_module
from app.config.settings import settings
from app.core.model_client import ModelClient
from app.core.model_routing import ModelRoutingRules
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


class ProviderError(RuntimeError):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


class SequencedCompletions:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=outcome)
                )
            ],
            usage=SimpleNamespace(total_tokens=100),
        )


@pytest.fixture(autouse=True)
def reset_model_health():
    ModelRoutingRules.reset_health()
    yield
    ModelRoutingRules.reset_health()


def test_client_uses_bounded_timeout_without_hidden_sdk_retries(monkeypatch):
    captured: dict = {}

    def fake_openai(**kwargs):
        captured.update(kwargs)
        return FakeOpenAI("")

    monkeypatch.setattr(model_client_module, "OpenAI", fake_openai)

    ModelClient(
        api_key="test-key",
        base_url="https://example.invalid/v1",
    )

    assert captured["timeout"] == settings.model_request_timeout_seconds
    assert captured["max_retries"] == 0


def test_chat_uses_openai_compatible_chat_completions_api():
    client = FakeOpenAI("生成结果")

    result = ModelClient(client=client).chat(
        [{"role": "user", "content": "生成本章"}],
        temperature=0.1,
        max_tokens=1234,
    )

    assert result == "生成结果"
    expected_model = ModelRoutingRules.load().models_for_task(
        "default", settings.llm_model
    )[0]
    assert client.chat.completions.calls == [
        {
            "model": expected_model,
            "messages": [{"role": "user", "content": "生成本章"}],
            "temperature": 0.1,
            "max_tokens": 1234,
            "extra_body": {"thinking": {"type": "disabled"}},
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
        ("extraction", "deepseek-v4-flash"),
        ("classification", "deepseek-v4-flash"),
        ("writing", "deepseek-v4-pro"),
        ("review", "deepseek-v4-pro"),
        ("unknown", "deepseek-v4-flash"),
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
    assert events[0][2]["model"] == "deepseek-v4-pro"
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
        call_limit=3,
        token_limit=180000,
    )

    assert limits == {
        "model_call_limit": 3,
        "model_token_limit": 180000,
    }
    assert captured["params"] == (3, 180000, run_id)


def test_retryable_provider_error_switches_to_rule_fallback():
    completions = SequencedCompletions(
        [ProviderError("insufficient quota", 429), "备用模型完成"]
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )

    result = ModelClient(client=client).chat(
        [{"role": "user", "content": "生成章节"}],
        task="writing",
    )

    assert result == "备用模型完成"
    assert len(completions.calls) == 2
    assert completions.calls[0]["model"] == "deepseek-v4-pro"
    assert completions.calls[1]["model"] == "deepseek-v4-flash"


def test_forbidden_model_switches_to_rule_fallback():
    completions = SequencedCompletions(
        [ProviderError("model access forbidden", 403), "备用模型完成"]
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )

    result = ModelClient(client=client).chat(
        [{"role": "user", "content": "生成章节"}],
        task="writing",
    )

    assert result == "备用模型完成"
    assert len(completions.calls) == 2
    assert completions.calls[0]["model"] == "deepseek-v4-pro"
    assert completions.calls[1]["model"] == "deepseek-v4-flash"


def test_zero_usage_failures_can_scan_ten_model_pool():
    completions = SequencedCompletions(
        [
            *[
                ProviderError("model access forbidden", 403)
                for _ in range(9)
            ],
            "第十个模型完成",
        ]
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )

    result = ModelClient(client=client).chat(
        [{"role": "user", "content": "生成章节"}],
        task="writing",
    )

    assert result == "第十个模型完成"
    assert len(completions.calls) == 10
    assert len(
        {item["model"] for item in completions.calls}
    ) == 10


def test_billable_failures_stop_after_rule_budget():
    completions = SequencedCompletions(
        [
            ProviderError("temporary upstream error", 500),
            ProviderError("temporary upstream error", 500),
            "不应调用",
        ]
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )

    with pytest.raises(ProviderError, match="upstream"):
        ModelClient(client=client).chat(
            [{"role": "user", "content": "生成章节"}],
            task="writing",
        )

    assert len(completions.calls) == 2


def test_permission_failure_cools_model_for_next_request():
    first = SequencedCompletions(
        [ProviderError("model access forbidden", 403), "备用完成"]
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=first)
    )
    ModelClient(client=client).chat(
        [{"role": "user", "content": "第一次"}],
        task="writing",
    )

    second = FakeOpenAI("第二次完成")
    ModelClient(client=second).chat(
        [{"role": "user", "content": "第二次"}],
        task="writing",
    )

    assert second.chat.completions.calls[0]["model"] == "deepseek-v4-flash"


def test_non_retryable_provider_error_does_not_switch_model():
    completions = SequencedCompletions(
        [ProviderError("invalid request body", 400)]
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )

    with pytest.raises(ProviderError, match="invalid request"):
        ModelClient(client=client).chat(
            [{"role": "user", "content": "生成章节"}],
            task="writing",
        )

    assert len(completions.calls) == 1

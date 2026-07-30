from types import SimpleNamespace

import pytest

from app.config.settings import settings
from app.core.model_client import ModelClient


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

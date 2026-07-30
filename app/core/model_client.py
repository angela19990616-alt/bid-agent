from typing import Any

from openai import OpenAI

from app.config.settings import settings


class ModelConfigurationError(RuntimeError):
    pass


class ModelClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        client: Any | None = None,
    ):
        if client is not None:
            self.client = client
            return
        resolved_key = api_key or settings.model_api_key
        if not resolved_key:
            raise ModelConfigurationError(
                "未配置 DASHSCOPE_API_KEY 或 OPENAI_API_KEY"
            )
        self.client = OpenAI(
            api_key=resolved_key,
            base_url=base_url or settings.openai_base_url,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        embeddings: list[list[float]] = []
        batch_size = settings.embedding_batch_size
        for start in range(0, len(texts), batch_size):
            response = self.client.embeddings.create(
                model=settings.embedding_model,
                input=texts[start : start + batch_size],
                dimensions=settings.embedding_dimensions,
                encoding_format="float",
            )
            ordered = sorted(response.data, key=lambda item: item.index)
            embeddings.extend(item.embedding for item in ordered)
        return embeddings

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 4000,
        task: str = "default",
    ) -> str:
        response = self.client.chat.completions.create(
            model=settings.model_for_task(task),
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("模型返回了空内容")
        return content

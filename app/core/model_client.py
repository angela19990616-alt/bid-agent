from typing import Any
from uuid import UUID

from openai import OpenAI

from app.config.settings import settings
from app.core.model_routing import ModelRoutingRules
from app.services.model_budget_service import ModelBudgetService


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
            timeout=settings.model_request_timeout_seconds,
            # Retry and model switching are controlled by ModelRoutingRules.
            max_retries=0,
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
        workflow_run_id: UUID | None = None,
    ) -> str:
        routing = ModelRoutingRules.load()
        models = routing.models_for_task(
            task,
            settings.model_for_task(task),
        )
        last_error: Exception | None = None
        for index, model in enumerate(models):
            reservation = None
            if workflow_run_id is not None:
                reservation = ModelBudgetService.reserve(
                    workflow_run_id,
                    task=task,
                    model=model,
                    estimated_tokens=ModelBudgetService.estimate(
                        messages, max_tokens
                    ),
                )
            try:
                response = self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as exc:
                last_error = exc
                if reservation is not None:
                    ModelBudgetService.finish(
                        reservation,
                        actual_tokens=(
                            0 if routing.known_zero_usage(exc) else None
                        ),
                        error_type=type(exc).__name__,
                    )
                if (
                    index + 1 >= len(models)
                    or not routing.is_retryable(exc)
                ):
                    raise
                continue
            if reservation is not None:
                usage = getattr(response, "usage", None)
                ModelBudgetService.finish(
                    reservation,
                    actual_tokens=getattr(usage, "total_tokens", None),
                )
            content = response.choices[0].message.content
            if not content:
                raise RuntimeError("模型返回了空内容")
            return content
        if last_error is not None:
            raise last_error
        raise RuntimeError("没有可用的模型路由。")

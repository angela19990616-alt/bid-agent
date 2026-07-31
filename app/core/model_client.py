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
        self._injected_client = client
        if client is not None:
            self.client = client
            return
        resolved_key = api_key or settings.model_api_key
        if not resolved_key and not settings.deepseek_api_key:
            raise ModelConfigurationError(
                "未配置 DEEPSEEK_API_KEY、DASHSCOPE_API_KEY 或 OPENAI_API_KEY"
            )
        self.client = (
            OpenAI(
                api_key=resolved_key,
                base_url=base_url or settings.openai_base_url,
                timeout=settings.model_request_timeout_seconds,
                # Retry and switching are controlled by ModelRoutingRules.
                max_retries=0,
            )
            if resolved_key
            else None
        )
        self.deepseek_client = (
            OpenAI(
                api_key=settings.deepseek_api_key,
                base_url=settings.deepseek_base_url,
                timeout=settings.model_request_timeout_seconds,
                max_retries=0,
            )
            if settings.deepseek_api_key
            else None
        )

    def _client_for_model(
        self, model: str, routing: ModelRoutingRules
    ) -> Any | None:
        if self._injected_client is not None:
            return self._injected_client
        if routing.provider_for(model) == "deepseek":
            return self.deepseek_client
        return self.client

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self.client is None:
            raise ModelConfigurationError(
                "向量检索需要配置 DASHSCOPE_API_KEY 或 OPENAI_API_KEY"
            )
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
        models = [
            model
            for model in models
            if self._client_for_model(model, routing) is not None
        ]
        if not models:
            raise RuntimeError(
                "当前任务的模型均处于临时冷却状态，请稍后重试。"
            )
        last_error: Exception | None = None
        billable_failures = 0
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
                provider_client = self._client_for_model(model, routing)
                if provider_client is None:
                    continue
                request_options: dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": routing.output_limit(
                        model, max_tokens
                    ),
                }
                if (
                    routing.provider_for(model) == "deepseek"
                    and model.startswith("deepseek-v4-")
                ):
                    request_options["extra_body"] = {
                        "thinking": {
                            "type": (
                                "enabled"
                                if model == "deepseek-v4-pro"
                                and task in {"writing", "review"}
                                else "disabled"
                            )
                        }
                    }
                response = provider_client.chat.completions.create(
                    **request_options,
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
                zero_usage = routing.known_zero_usage(exc)
                routing.mark_failure(model, exc)
                if not zero_usage:
                    billable_failures += 1
                if (
                    index + 1 >= len(models)
                    or not routing.is_retryable(exc)
                    or (
                        billable_failures
                        >= routing.max_billable_failures
                    )
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
            routing.mark_success(task, model)
            return content
        if last_error is not None:
            raise last_error
        raise RuntimeError("没有可用的模型路由。")

from typing import Any

from app.services.config_service import ConfigService


class LLMFactory:
    @staticmethod
    def create(config_key: str = "llm.default") -> Any:
        config = ConfigService.get(config_key)

        if config is None:
            raise RuntimeError(f"LLM configuration not found: {config_key}")

        provider = config.get("provider")
        model = config.get("model")
        temperature = config.get("temperature", 0.2)
        max_tokens = config.get("max_tokens", 4000)

        if not provider:
            raise ValueError("LLM provider is missing")

        if not model:
            raise ValueError("LLM model is missing")

        if provider in {"dashscope", "openai"}:
            return {
                "provider": provider,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }

        raise ValueError(f"Unsupported LLM provider: {provider}")

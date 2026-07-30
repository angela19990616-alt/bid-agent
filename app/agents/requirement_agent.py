from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from uuid import UUID

from app.core.model_client import ModelClient
from app.rules.engine import RuleDocument, RuleEngine
from app.services.model_budget_service import ModelBudgetExceeded


IMPORTANCE_LEVELS = {"low", "medium", "high"}
logger = logging.getLogger("bid-agent.requirement-agent")
LIST_ITEM = re.compile(
    r"^(?:[（(]?[一二三四五六七八九十\d]+[）).、．.]|"
    r"\d+(?:\.\d+)+|[①②③④⑤⑥⑦⑧⑨⑩])"
)
TOC_LINE = re.compile(
    r"^第[一二三四五六七八九十百\d]+章.{1,80}?\d{1,3}$"
)
CHAPTER_HEADING = re.compile(
    r"^第[一二三四五六七八九十百\d]+章(?:\s|　)*.{0,80}$"
)
SECTION_HEADING = re.compile(
    r"^[一二三四五六七八九十百]+[、.．]\s*.{1,60}$"
)
TRAILING_PAGE_NUMBER = re.compile(r".{3,80}\D\d{1,3}$")
@dataclass(frozen=True)
class RequirementEvidence:
    source_id: UUID
    source_ref: str
    text: str
    context: str


@dataclass(frozen=True)
class AgentRequirement:
    source_id: UUID
    title: str
    normalized_text: str
    quote: str
    requirement_type: str
    importance: str
    confidence: float


class RequirementAgentError(RuntimeError):
    pass


class RequirementResponseFormatError(RequirementAgentError):
    pass


class RequirementAgent:
    def __init__(
        self,
        model_client: ModelClient | None = None,
        *,
        batch_size: int = 30,
        recovery_batch_size: int = 8,
    ):
        self.model_client = model_client
        self.batch_size = batch_size
        self.recovery_batch_size = recovery_batch_size

    @property
    def client(self) -> ModelClient:
        if self.model_client is None:
            self.model_client = ModelClient()
        return self.model_client

    def extract(
        self,
        sources: list[dict],
        rules: RuleDocument | None = None,
        workflow_run_id: UUID | None = None,
    ) -> list[AgentRequirement]:
        active = rules or RuleEngine().load_default("extraction")
        evidence = self._select_evidence(sources, active.content)
        if not evidence:
            return []
        extracted: list[AgentRequirement] = []
        for start in range(0, len(evidence), self.batch_size):
            batch = evidence[start : start + self.batch_size]
            extracted.extend(
                self._extract_batch(batch, active, workflow_run_id)
            )
        return extracted

    def _extract_batch(
        self,
        batch: list[RequirementEvidence],
        rules: RuleDocument,
        workflow_run_id: UUID | None = None,
    ) -> list[AgentRequirement]:
        try:
            return self._extract_batch_once(
                batch, rules, workflow_run_id=workflow_run_id
            )
        except RequirementResponseFormatError:
            logger.warning(
                "Model returned malformed requirement JSON; "
                "retrying in %s-item recovery batches",
                self.recovery_batch_size,
            )
        recovered: list[AgentRequirement] = []
        for start in range(0, len(batch), self.recovery_batch_size):
            recovery_batch = batch[
                start : start + self.recovery_batch_size
            ]
            try:
                recovered.extend(
                    self._extract_batch_once(
                        recovery_batch,
                        rules,
                        strict_retry=True,
                        workflow_run_id=workflow_run_id,
                    )
                )
            except RequirementResponseFormatError:
                logger.error(
                    "Model returned malformed JSON for a recovery "
                    "batch; applying deterministic fallbacks"
                )
                recovered.extend(
                    self._apply_deterministic_fallbacks(
                        recovery_batch,
                        [],
                        rules.content,
                    )
                )
        return recovered

    def _extract_batch_once(
        self,
        batch: list[RequirementEvidence],
        rules: RuleDocument,
        *,
        strict_retry: bool = False,
        workflow_run_id: UUID | None = None,
    ) -> list[AgentRequirement]:
        source_map = {item.source_ref: item for item in batch}
        content = [
            {
                "source_ref": item.source_ref,
                "context": item.context,
                "text": item.text,
            }
            for item in batch
        ]
        try:
            response = self.client.chat(
                [
                    {
                        "role": "system",
                        "content": self._system_prompt(rules),
                    },
                    {
                        "role": "user",
                        "content": (
                            "请审查以下候选原文并返回 JSON。"
                            "不要解释，不要输出 Markdown。\n"
                            + (
                                "上一次响应不是合法 JSON。此次只返回"
                                "一个完整 JSON 对象，确保所有字符串、"
                                "逗号、括号均闭合。\n"
                                if strict_retry
                                else ""
                            )
                            + json.dumps(content, ensure_ascii=False)
                        ),
                    },
                ],
                temperature=0,
                max_tokens=6000,
                task="extraction",
                workflow_run_id=workflow_run_id,
            )
        except ModelBudgetExceeded:
            raise
        except Exception as exc:
            raise RequirementAgentError(
                "Requirement Agent 模型调用失败。"
            ) from exc
        try:
            payload = self._parse_json(response)
        except (json.JSONDecodeError, ValueError) as exc:
            raise RequirementResponseFormatError(
                "Requirement Agent 返回格式不完整。"
            ) from exc

        results: list[AgentRequirement] = []
        for raw in payload.get("requirements", []):
            if not isinstance(raw, dict):
                continue
            item = self._validate_item(raw, source_map, rules.content)
            if item is not None:
                results.append(item)
        return self._apply_deterministic_fallbacks(
            batch,
            results,
            rules.content,
        )

    @classmethod
    def _apply_deterministic_fallbacks(
        cls,
        batch: list[RequirementEvidence],
        extracted: list[AgentRequirement],
        config: dict,
    ) -> list[AgentRequirement]:
        results = list(extracted)
        fallback_rules = config.get("deterministic_fallbacks", [])
        covered = {
            (item.source_id, item.requirement_type) for item in results
        }
        for fallback in fallback_rules:
            requirement_type = str(fallback["requirement_type"])
            patterns = [
                re.compile(pattern)
                for pattern in fallback.get("any_patterns", [])
            ]
            exclude_patterns = [
                re.compile(pattern)
                for pattern in fallback.get("exclude_patterns", [])
            ]
            context_markers = fallback.get("context_markers", [])
            for evidence in batch:
                if (evidence.source_id, requirement_type) in covered:
                    continue
                if patterns and not any(
                    pattern.search(evidence.text) for pattern in patterns
                ):
                    continue
                if any(
                    pattern.search(evidence.text)
                    for pattern in exclude_patterns
                ):
                    continue
                context = f"{evidence.context} {evidence.text}"
                if context_markers and not any(
                    marker in context for marker in context_markers
                ):
                    continue
                concise = evidence.text.strip("。；;：:")
                title = (
                    f"{fallback['title_prefix']}：{concise}"
                )[:80]
                normalized = (
                    f"{fallback['normalized_prefix']}{concise}"
                )[:1000]
                results.append(
                    AgentRequirement(
                        source_id=evidence.source_id,
                        title=title,
                        normalized_text=normalized,
                        quote=evidence.text[:1000],
                        requirement_type=requirement_type,
                        importance=str(
                            fallback.get("importance", "high")
                        ),
                        confidence=float(
                            fallback.get("confidence", 0.8)
                        ),
                    )
                )
                covered.add((evidence.source_id, requirement_type))
        return results

    @staticmethod
    def _system_prompt(rules: RuleDocument) -> str:
        return (
            f"{rules.content['model_instruction']}\n"
            "以下是本次运行已加载的版本化提取规则，必须逐项遵守：\n"
            + json.dumps(rules.content, ensure_ascii=False)
        )

    @classmethod
    def _validate_item(
        cls,
        raw: dict,
        source_map: dict[str, RequirementEvidence],
        config: dict,
    ) -> AgentRequirement | None:
        source = source_map.get(str(raw.get("source_ref", "")))
        if source is None:
            return None
        title = cls._clean(str(raw.get("title", "")))[:80]
        normalized = cls._clean(str(raw.get("requirement", "")))[:1000]
        evidence = cls._clean(str(raw.get("evidence", "")))
        requirement_type = str(raw.get("type", ""))
        importance = str(raw.get("importance", "medium"))
        try:
            confidence = float(raw.get("confidence", 0))
        except (TypeError, ValueError):
            return None

        if not 4 <= len(title) <= 80 or not 8 <= len(normalized) <= 1000:
            return None
        if cls.is_structural_noise(title, config) or cls.is_structural_noise(
            normalized, config
        ):
            return None
        if requirement_type not in config["types"]:
            return None
        if requirement_type == "scoring" and any(
            re.search(pattern, source.text)
            for fallback in config.get("deterministic_fallbacks", [])
            if fallback.get("requirement_type") == "scoring"
            for pattern in fallback.get("exclude_patterns", [])
        ):
            return None
        if importance not in IMPORTANCE_LEVELS:
            return None
        if cls._canonical(title) == cls._canonical(normalized):
            return None
        if cls._is_internal_instruction(source.text, config):
            return None
        if not cls._is_actionable(normalized, requirement_type, config):
            return None
        if not evidence or evidence not in source.text:
            evidence = source.text
        return AgentRequirement(
            source_id=source.source_id,
            title=title,
            normalized_text=normalized,
            quote=evidence[:1000],
            requirement_type=requirement_type,
            importance=importance,
            confidence=min(max(confidence, 0.5), 0.98),
        )

    @classmethod
    def _select_evidence(
        cls,
        sources: list[dict],
        config: dict,
    ) -> list[RequirementEvidence]:
        selected: list[RequirementEvidence] = []
        recent: list[str] = []
        section_heading = ""
        for index, source in enumerate(sources, start=1):
            text = cls._clean(str(source["content"]))
            if not text:
                continue
            is_heading = cls._looks_like_heading(text, config)
            if cls.is_structural_noise(text, config):
                if is_heading and not TOC_LINE.match(text):
                    section_heading = text
                    recent.append(text)
                continue
            if is_heading:
                section_heading = text
            context = " / ".join(
                [section_heading, *recent[-3:]]
            )[-600:]
            direct = any(
                marker in text for marker in config["candidate_markers"]
            )
            fallback_direct = any(
                any(
                    re.search(pattern, text)
                    for pattern in fallback.get("any_patterns", [])
                )
                and (
                    not fallback.get("context_markers")
                    or any(
                        marker in f"{context} {text}"
                        for marker in fallback["context_markers"]
                    )
                )
                for fallback in config.get(
                    "deterministic_fallbacks", []
                )
            )
            contextual_list = bool(LIST_ITEM.match(text)) and any(
                marker in context for marker in config["context_markers"]
            )
            if direct or fallback_direct or contextual_list:
                selected.append(
                    RequirementEvidence(
                        source_id=source["id"],
                        source_ref=f"S{index}",
                        text=text[:1600],
                        context=context,
                    )
                )
            recent.append(text[:180])
            if len(recent) > 6:
                recent.pop(0)
            if len(selected) >= int(
                config.get("max_evidence_candidates", 500)
            ):
                break
        return selected

    @classmethod
    def is_structural_noise(
        cls,
        text: str,
        config: dict | None = None,
    ) -> bool:
        active = config or RuleEngine().load_default("extraction").content
        value = cls._clean(text)
        compact = value.replace(" ", "")
        if not value or compact in {
            item.replace(" ", "") for item in active["ignore_labels"]
        }:
            return True
        if len(value) < 4 or value.isdigit():
            return True
        if TOC_LINE.match(value):
            return True
        if CHAPTER_HEADING.match(value):
            return True
        if SECTION_HEADING.match(value) and len(value) <= 35:
            return True
        if (
            TRAILING_PAGE_NUMBER.match(value)
            and any(
                value.startswith(f"第{number}章")
                for number in "一二三四五六七八九十"
            )
        ):
            return True
        return False

    @staticmethod
    def _looks_like_heading(text: str, config: dict) -> bool:
        suffixes = tuple(config["heading_suffixes"])
        return bool(
            CHAPTER_HEADING.match(text)
            or SECTION_HEADING.match(text)
            or (
                len(text) <= 60
                and re.match(
                    r"^[★*]?[（(]?[一二三四五六七八九十\d]+[）)、.．]",
                    text,
                )
                and text.rstrip("：:").endswith(
                    suffixes
                )
            )
            or (
                len(text) <= 60
                and text.rstrip("：:").endswith(
                    suffixes
                )
            )
        )

    @staticmethod
    def _parse_json(value: str) -> dict:
        cleaned = value.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("模型未返回 JSON 对象")
        payload = json.loads(cleaned[start : end + 1])
        if not isinstance(payload, dict) or not isinstance(
            payload.get("requirements"), list
        ):
            raise ValueError("模型 JSON 缺少 requirements 数组")
        return payload

    @staticmethod
    def _is_actionable(
        text: str,
        requirement_type: str,
        config: dict,
    ) -> bool:
        if text.startswith(tuple(config["allowed_prefixes"])):
            return True
        return requirement_type == "scoring" and (
            text.startswith(("供应商", "投标人"))
            and any(marker in text for marker in ("得分", "评分", "加分"))
        )

    @staticmethod
    def _is_internal_instruction(text: str, config: dict) -> bool:
        actors = "|".join(
            re.escape(item) for item in config["internal_actors"]
        )
        internal_action = re.search(
            rf"(?:{actors})"
            r".{0,16}?(?:应当|(?<!响)应(?!响)|须|不得|可以|负责)",
            text,
        )
        supplier_action = re.search(
            r"(?:供应商|投标人).{0,10}?"
            r"(?:应当|(?<!响)应(?!响)|须|必须|不得|不能|拒绝|未能|未按)",
            text,
        )
        return bool(internal_action and not supplier_action)

    @staticmethod
    def _clean(value: str) -> str:
        return " ".join(value.split()).strip(" -—\t")

    @staticmethod
    def _canonical(value: str) -> str:
        return re.sub(r"[\W_]+", "", value).lower()

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from uuid import UUID

from app.core.model_client import ModelClient


REQUIREMENT_TYPES = {
    "technical",
    "scoring",
    "delivery",
    "qualification",
    "compliance",
    "commercial",
}
IMPORTANCE_LEVELS = {"low", "medium", "high"}
ACTION_MARKERS = (
    "必须",
    "须",
    "应当",
    "不得",
    "不允许",
    "不接受",
    "无效",
    "否决",
    "响应文件",
    "供应商",
    "投标人",
    "报价",
    "提交",
    "提供",
    "具备",
    "具有",
    "评分",
    "得分",
    "交付",
    "验收",
    "服务要求",
    "技术要求",
    "商务要求",
    "服务内容",
    "成果要求",
)
RELEVANT_CONTEXT_MARKERS = (
    "响应文件",
    "资格",
    "证明材料",
    "评分",
    "技术",
    "服务",
    "商务",
    "报价",
    "交付",
    "验收",
    "成果",
    "供应商",
)
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
GENERIC_LABELS = {
    "目录",
    "目 录",
    "目    录",
    "序号",
    "采购内容",
    "单位",
    "数量",
    "备注",
    "说明和要求",
    "响应文件格式",
    "供应商资格证明材料",
}


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


class RequirementAgent:
    def __init__(
        self,
        model_client: ModelClient | None = None,
        *,
        batch_size: int = 80,
    ):
        self.model_client = model_client
        self.batch_size = batch_size

    @property
    def client(self) -> ModelClient:
        if self.model_client is None:
            self.model_client = ModelClient()
        return self.model_client

    def extract(self, sources: list[dict]) -> list[AgentRequirement]:
        evidence = self._select_evidence(sources)
        if not evidence:
            return []
        extracted: list[AgentRequirement] = []
        for start in range(0, len(evidence), self.batch_size):
            batch = evidence[start : start + self.batch_size]
            extracted.extend(self._extract_batch(batch))
        return extracted

    def _extract_batch(
        self,
        batch: list[RequirementEvidence],
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
                        "content": self._system_prompt(),
                    },
                    {
                        "role": "user",
                        "content": (
                            "请审查以下候选原文并返回 JSON。"
                            "不要解释，不要输出 Markdown。\n"
                            + json.dumps(content, ensure_ascii=False)
                        ),
                    },
                ],
                temperature=0,
                max_tokens=7000,
            )
            payload = self._parse_json(response)
        except Exception as exc:
            raise RequirementAgentError(
                "Requirement Agent 调用或解析失败。"
            ) from exc

        results: list[AgentRequirement] = []
        for raw in payload.get("requirements", []):
            if not isinstance(raw, dict):
                continue
            item = self._validate_item(raw, source_map)
            if item is not None:
                results.append(item)
        return results

    @staticmethod
    def _system_prompt() -> str:
        return """
你是 Requirement Agent，任务是从中国政府采购/招标文件中找出“供应商在投标或
响应文件中必须做什么、写什么、提供什么、承诺什么，以及如何被评分或否决”。

只保留能够指导编制或校核投标文件的具体要求：
1. 资格、证明材料、响应文件组成与格式、签字盖章、份数、密封、有效期；
2. 技术/服务/商务响应、成果交付、验收、工期、报价；
3. 评分点、加分条件、无效响应和否决条件。
4. 在“技术要求、服务内容、成果要求、商务要求”等标题下，即使原文省略
   “供应商”主语，清单中的工作、成果和方案内容也属于供应商义务，应保留。

最终结果必须直接服务于投标/响应文件编制或提交前校核。一般性廉洁纪律、采购
机构工作程序、成交后的合同备案和内部管理动作，如果不要求供应商在响应文件中
提供材料、作出承诺或形成技术/商务响应，则排除。

必须排除：
1. 目录行、章节标题、页码、表头、字段名、联系方式；
2. 项目背景、采购人或代理机构的内部流程、评审人员的动作；
3. 仅说明“详见某章”“供应商须知”“资格证明材料”等空泛标签；
4. 不能回答“供应商要做什么”的句子。

requirement 字段必须聚焦供应商动作，并以“供应商应”“供应商须”
“供应商不得”“响应文件应”或“报价应”之一开头。不要把采购人、代理机构、
谈判小组或评审委员会的动作写进 requirement。无效或否决条件应改写为供应商
应避免的具体行为。title 必须与 requirement 含义一致，尤其不得颠倒高于/低于、
多于/少于、之前/之后等方向。
“成果要求”中的报告、方案和文档是成交后的交付成果，应写为“供应商应提交/
交付……”，不得误写成“响应文件应包含……”。

输出严格 JSON：
{"requirements":[
  {
    "source_ref":"输入中的 source_ref",
    "title":"8-30字、动作型、让人一眼看懂的主题",
    "requirement":"以“供应商应/不得/响应文件应”表达的完整可执行要求",
    "type":"technical|scoring|delivery|qualification|compliance|commercial",
    "importance":"low|medium|high",
    "confidence":0.0到1.0,
    "evidence":"必须逐字来自该 source_ref 的最小充分原文片段"
  }
]}

同一原文含多条独立义务时可拆成多条；重复表述只保留信息更完整的一条。
不得补充原文没有的资质、参数、案例、日期或承诺。
""".strip()

    @classmethod
    def _validate_item(
        cls,
        raw: dict,
        source_map: dict[str, RequirementEvidence],
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
        if cls.is_structural_noise(title) or cls.is_structural_noise(
            normalized
        ):
            return None
        if requirement_type not in REQUIREMENT_TYPES:
            return None
        if importance not in IMPORTANCE_LEVELS:
            return None
        if cls._canonical(title) == cls._canonical(normalized):
            return None
        if cls._is_internal_instruction(source.text):
            return None
        if not cls._is_actionable(normalized, requirement_type):
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
    ) -> list[RequirementEvidence]:
        selected: list[RequirementEvidence] = []
        recent: list[str] = []
        section_heading = ""
        for index, source in enumerate(sources, start=1):
            text = cls._clean(str(source["content"]))
            if not text:
                continue
            is_heading = cls._looks_like_heading(text)
            if cls.is_structural_noise(text):
                if is_heading and not TOC_LINE.match(text):
                    section_heading = text
                    recent.append(text)
                continue
            if is_heading:
                section_heading = text
            context = " / ".join(
                [section_heading, *recent[-3:]]
            )[-600:]
            direct = any(marker in text for marker in ACTION_MARKERS)
            contextual_list = bool(LIST_ITEM.match(text)) and any(
                marker in context for marker in RELEVANT_CONTEXT_MARKERS
            )
            if direct or contextual_list:
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
            if len(selected) >= 500:
                break
        return selected

    @classmethod
    def is_structural_noise(cls, text: str) -> bool:
        value = cls._clean(text)
        compact = value.replace(" ", "")
        if not value or compact in {item.replace(" ", "") for item in GENERIC_LABELS}:
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
    def _looks_like_heading(text: str) -> bool:
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
                    ("要求", "内容", "材料", "组成", "成果")
                )
            )
            or (
                len(text) <= 60
                and text.rstrip("：:").endswith(
                    ("要求", "条件", "内容", "材料", "组成", "成果")
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
    def _is_actionable(text: str, requirement_type: str) -> bool:
        if text.startswith(
            (
                "供应商应",
                "供应商须",
                "供应商不得",
                "投标人应",
                "投标人须",
                "投标人不得",
                "响应文件应",
                "响应文件须",
                "报价应",
            )
        ):
            return True
        return requirement_type == "scoring" and (
            text.startswith(("供应商", "投标人"))
            and any(marker in text for marker in ("得分", "评分", "加分"))
        )

    @staticmethod
    def _is_internal_instruction(text: str) -> bool:
        internal_action = re.search(
            r"(?:谈判小组|评审委员会|采购人|采购代理机构)"
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

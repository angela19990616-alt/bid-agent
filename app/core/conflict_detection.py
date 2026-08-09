from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ConflictCandidate:
    topic: str
    conflict_type: str
    description: str
    risk_priority: str
    confidence: float


class ConflictDetectionEngine:
    """Conservative local comparison before any optional model review."""

    TOPICS = {
        "服务期限": (
            "服务期限", "服务周期", "履约期限", "合同期限",
            "日历天", "个月内", "个月完成",
        ),
        "成果数量": ("成果数量", "提交份数", "纸质版", "电子版"),
        "验收标准": ("验收标准", "验收条件", "验收合格", "验收依据"),
        "服务范围": ("服务范围", "工作范围", "服务内容", "工作内容"),
        "付款条件": ("付款", "支付", "预付款", "进度款"),
        "违约责任": ("违约", "违约金", "赔偿责任"),
        "技术指标": ("性能", "并发", "响应时间", "精度", "技术指标"),
    }
    STRICT_CROSS_SOURCE_TOPICS = {
        "服务期限", "成果数量", "验收标准", "服务范围", "付款条件", "违约责任"
    }
    ENHANCEMENT = ("加分", "得分", "优于", "提前完成", "增强", "额外")
    PRIORITY = {
        "服务期限": "P0", "成果数量": "P1", "验收标准": "P0",
        "服务范围": "P1", "付款条件": "P0", "违约责任": "P0",
        "技术指标": "P1",
    }
    NUMBER = re.compile(r"(?<![A-Za-z])(\d+(?:\.\d+)?)\s*(日历天|天|个月|月|年|份|套|%|元|万元)?")

    @classmethod
    def topic(cls, text: str) -> str | None:
        for topic, keywords in cls.TOPICS.items():
            if any(keyword in text for keyword in keywords):
                return topic
        return None

    @classmethod
    def _values(cls, text: str) -> set[tuple[Decimal, str]]:
        return {
            (Decimal(number), unit or "")
            for number, unit in cls.NUMBER.findall(text)
        }

    @classmethod
    def compare(
        cls,
        *,
        text_a: str,
        text_b: str,
        role_a: str = "unknown",
        role_b: str = "unknown",
    ) -> ConflictCandidate | None:
        topic_a = cls.topic(text_a)
        topic_b = cls.topic(text_b)
        if topic_a and topic_b is None and any(
            word in text_b for word in cls.ENHANCEMENT
        ):
            topic_b = topic_a
        if topic_b and topic_a is None and any(
            word in text_a for word in cls.ENHANCEMENT
        ):
            topic_a = topic_b
        if topic_a is None or topic_a != topic_b:
            return None
        topic = topic_a
        if any(word in text_a + text_b for word in cls.ENHANCEMENT):
            return ConflictCandidate(
                topic, "positive_difference",
                "基础要求与评分增强条件并存，不构成互斥冲突。",
                "P1", 0.94,
            )
        values_a, values_b = cls._values(text_a), cls._values(text_b)
        if values_a and values_b and values_a != values_b:
            cross_procurement_contract = {
                role_a, role_b
            } == {"procurement_requirement", "contract"}
            kind = (
                "true_conflict"
                if cross_procurement_contract
                and topic in cls.STRICT_CROSS_SOURCE_TOPICS
                else "potential_conflict"
            )
            return ConflictCandidate(
                topic, kind,
                "同一事项出现不同量化口径，保留两处原文等待复核。",
                cls.PRIORITY.get(topic, "P2"),
                0.95 if kind == "true_conflict" else 0.72,
            )
        if text_a == text_b:
            return None
        return ConflictCandidate(
            topic, "compatible_difference",
            "同一事项表述不同，但未发现互斥的量化口径。",
            "P3", 0.86,
        )

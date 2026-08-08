from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row

from app.database.db import connect


@dataclass(frozen=True)
class CaseFactCandidate:
    canonical_key: str
    value: str
    source_title: str
    source_excerpt: str
    source_location: str
    confidence: float
    match_count: int
    alternatives: tuple[str, ...] = ()


class CaseFactResolver:
    """Find review-only field candidates in the five private bid examples.

    Historical bids are evidence candidates, never verified enterprise facts.
    A user confirmation is required before formal delivery can use a value.
    """

    PATTERNS: dict[str, tuple[str, ...]] = {
        "bidder_name": (
            r"(?:供应商|投标人|响应人|参选人)(?:名称)?(?:（[^\n）]*）)?\s*[|:：]?\s*([^\n|]{4,60}?(?:有限责任公司|有限公司|事务所))",
            r"我方[（(]?([^\n）)]{4,60}?(?:有限责任公司|有限公司))[）)]?",
        ),
        "legal_representative": (
            r"法定代表人(?:姓名)?\s*[|:：]?\s*([\u4e00-\u9fff·]{2,8})",
        ),
        "authorized_representative": (
            r"(?:现委托|授权)([\u4e00-\u9fff·]{2,8})(?:为|，|作为)",
            r"(?:委托代理人|授权代表)(?:姓名)?\s*[|:：]?\s*([\u4e00-\u9fff·]{2,8})",
        ),
        "registered_address": (
            r"(?:注册地址|供应商地址|投标人地址)\s*[|:：]?\s*([^\n|]{6,100})",
        ),
        "postal_code": (
            r"邮政编码\s*[|:：]?\s*(\d{6})",
        ),
        "contact_person": (
            r"(?:联系人|项目联系人)\s*[|:：]?\s*([\u4e00-\u9fff·]{2,8})",
        ),
        "contact_phone": (
            r"(?:联系电话|手机|电话)\s*[|:：]?\s*((?:\+?86[- ]?)?(?:1\d{10}|0\d{2,3}[- ]?\d{7,8}))",
        ),
        "fax": (r"传\s*真\s*[|:：]?\s*(0\d{2,3}[- ]?\d{7,8})",),
        "website": (r"(?:网址|网站)\s*[|:：]?\s*(https?://[^\s|]+|www\.[^\s|]+)",),
        "enterprise_qualification": (
            r"((?:已|现已)?在全国投资项目在线审批监管平台[^\n|]{0,60}?备案)",
        ),
        "bank_account": (
            r"(?:银行账号|账号)\s*[|:：]?\s*(\d{8,30})",
        ),
        "bid_round": (
            r"((?:第)?[一二三四五六七八九十\d]+轮)(?:报价|谈判)",
        ),
    }

    def resolve(self, project_id: UUID) -> dict[str, CaseFactCandidate]:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT k.title, k.content
                    FROM enterprise_knowledge k
                    JOIN projects p ON p.organization_key = k.organization_key
                    WHERE p.id = %s
                      AND k.status = 'active'
                      AND k.permission_scope = 'organization_private'
                      AND k.category = 'historical_bid'
                      AND COALESCE(k.metadata->>'source_role', '') IN (
                        'historical_case_proposal', 'response_content'
                      )
                    ORDER BY k.updated_at DESC
                    LIMIT 20
                    """,
                    (project_id,),
                )
                entries = [dict(row) for row in cursor.fetchall()]
        return self.extract(entries)

    @classmethod
    def extract(cls, entries: list[dict[str, Any]]) -> dict[str, CaseFactCandidate]:
        matches: dict[str, list[tuple[str, str, str, str]]] = defaultdict(list)
        for entry in entries:
            text = str(entry.get("content") or "")
            title = str(entry.get("title") or "历史投标案例")
            for key, patterns in cls.PATTERNS.items():
                for pattern in patterns:
                    for found in re.finditer(pattern, text, re.IGNORECASE):
                        value = cls._clean(found.group(1))
                        if not cls._usable(value):
                            continue
                        start = max(0, found.start() - 90)
                        end = min(len(text), found.end() + 130)
                        excerpt = re.sub(r"\s+", " ", text[start:end]).strip()
                        paragraph_start = text.count("\n", 0, found.start()) + 1
                        paragraph_end = text.count("\n", 0, found.end()) + 1
                        location = (
                            f"原文第 {paragraph_start} 段"
                            if paragraph_start == paragraph_end
                            else f"原文第 {paragraph_start}-{paragraph_end} 段"
                        )
                        matches[key].append((value, title, excerpt, location))
        result: dict[str, CaseFactCandidate] = {}
        for key, items in matches.items():
            counts = Counter(value for value, _, _, _ in items)
            value, count = counts.most_common(1)[0]
            source = next(item for item in items if item[0] == value)
            alternatives = tuple(item for item, _ in counts.most_common()[1:4])
            result[key] = CaseFactCandidate(
                canonical_key=key,
                value=value,
                source_title=source[1],
                source_excerpt=source[2],
                source_location=source[3],
                confidence=min(0.92, 0.55 + count * 0.08),
                match_count=count,
                alternatives=alternatives,
            )
        return result

    @staticmethod
    def _clean(value: str) -> str:
        return re.sub(r"[\s_·…]+$", "", re.sub(r"\s+", " ", value)).strip(" :：|（）()")

    @staticmethod
    def _usable(value: str) -> bool:
        if not value or len(value) > 120:
            return False
        lowered = value.lower()
        return not any(token in lowered for token in (
            "xxx", "填写", "加盖", "签字", "法定代表人或",
            "姓名", "代表人", "委托代理人",
        ))

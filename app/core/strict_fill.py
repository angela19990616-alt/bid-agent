from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class FillStatus(StrEnum):
    AUTO_FILL = "AUTO_FILL"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    MISSING = "MISSING"


class DataSensitivity(StrEnum):
    NORMAL = "normal"
    SENSITIVE = "sensitive"
    HIGHLY_SENSITIVE = "highly_sensitive"


@dataclass(frozen=True)
class TemplateField:
    field_id: str
    label: str
    canonical_key: str
    required: bool
    source_location: str


@dataclass(frozen=True)
class EnterpriseFact:
    canonical_key: str
    value: str
    source_type: str
    source_reference: str
    confidence: float
    verified: bool
    sensitivity: DataSensitivity = DataSensitivity.NORMAL
    evidence_title: str | None = None
    evidence_excerpt: str | None = None
    evidence_location: str | None = None


@dataclass(frozen=True)
class FillDecision:
    field: TemplateField
    value: str | None
    source_type: str | None
    source_reference: str | None
    confidence: float
    status: FillStatus
    reason: str
    evidence_title: str | None = None
    evidence_excerpt: str | None = None
    evidence_location: str | None = None


class StrictFillDecisionEngine:
    """Makes deterministic fill decisions; it never invents enterprise facts."""

    NON_AUTHORITATIVE_FACT_SOURCES = {
        "historical_case",
        "proposal_memory",
        "generated_proposal",
    }
    EVIDENCE_REQUIRED_SOURCES = {"company_profile", "qualification"}
    PERSON_FIELDS = {
        "legal_representative",
        "authorized_representative",
        "contact_person",
    }
    PERSON_LABEL_TOKENS = (
        "法人", "法定代表人", "授权代表", "委托代理人",
        "代表人", "联系人", "姓名", "签字", "签名", "或",
    )
    FIELD_TYPES = {
        "project_name": ("project_name", "项目名称"),
        "project_number": ("project_identifier", "项目编号"),
        "bidder_name": ("organization_name", "企业名称"),
        "legal_representative": ("person_name", "姓名"),
        "authorized_representative": ("person_name", "姓名"),
        "contact_person": ("person_name", "姓名"),
        "date": ("date", "日期"),
        "registered_address": ("address", "地址"),
        "postal_code": ("postal_code", "邮政编码"),
        "contact_phone": ("phone", "电话号码"),
        "fax": ("fax", "传真号码"),
        "website": ("website", "网址"),
        "enterprise_qualification": ("qualification", "资质信息"),
        "bank_account": ("bank_account", "银行账号"),
        "bid_round": ("bid_round", "报价轮次"),
    }
    PLACEHOLDER_TOKENS = (
        "xxx", "xxxx", "填写", "请填", "待定", "待填写", "示例",
        "签字", "签名", "盖章", "加盖", "此处", "不适用",
    )

    @classmethod
    def field_type(cls, canonical_key: str) -> str:
        return cls.FIELD_TYPES.get(canonical_key, ("text", "文本"))[0]

    @classmethod
    def field_type_label(cls, canonical_key: str) -> str:
        return cls.FIELD_TYPES.get(canonical_key, ("text", "文本"))[1]

    @classmethod
    def value_matches_field_type(cls, canonical_key: str, value: str) -> bool:
        """Reject labels/instructions that only look like field values."""
        raw = str(value or "").strip()
        cleaned = re.sub(r"\s+", "", raw).strip(":：|_-")
        if not cleaned:
            return False
        lowered = cleaned.lower()
        if any(token in lowered for token in cls.PLACEHOLDER_TOKENS):
            return False
        if canonical_key in cls.PERSON_FIELDS:
            if any(token in cleaned for token in cls.PERSON_LABEL_TOKENS):
                return False
            return bool(re.fullmatch(r"[一-鿿·]{2,20}", cleaned))
        if canonical_key == "project_number":
            return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{2,79}", cleaned))
        if canonical_key == "bidder_name":
            return (
                4 <= len(cleaned) <= 100
                and bool(re.search(
                    r"(?:公司|集团|事务所|研究院|研究所|中心|分公司|"
                    r"合伙企业|协会|学会|委员会|大学|学院)$",
                    cleaned,
                ))
                and not any(token in cleaned for token in ("供应商", "投标人", "名称"))
            )
        if canonical_key == "postal_code":
            return bool(re.fullmatch(r"\d{6}", cleaned))
        if canonical_key in {"contact_phone", "fax"}:
            return bool(re.fullmatch(
                r"(?:\+?86[- ]?)?(?:1\d{10}|0\d{2,3}[- ]?\d{7,8})",
                raw.replace("（", "(").replace("）", ")"),
            ))
        if canonical_key == "website":
            return bool(re.fullmatch(
                r"(?:https?://|www\.)[^\s|]{4,200}", raw, re.IGNORECASE
            ))
        if canonical_key == "bank_account":
            return bool(re.fullmatch(r"\d{8,30}", cleaned))
        if canonical_key == "date":
            return bool(re.fullmatch(
                r"(?:20\d{2}[-/.](?:0?[1-9]|1[0-2])[-/.](?:0?[1-9]|[12]\d|3[01])|"
                r"20\d{2}年(?:0?[1-9]|1[0-2])月(?:0?[1-9]|[12]\d|3[01])日)",
                cleaned,
            ))
        if canonical_key == "bid_round":
            return bool(re.fullmatch(r"(?:第)?[一二三四五六七八九十\d]+轮", cleaned))
        if canonical_key == "registered_address":
            return (
                6 <= len(cleaned) <= 120
                and not any(token in cleaned for token in ("注册地址", "供应商地址", "投标人地址"))
            )
        if canonical_key == "enterprise_qualification":
            return (
                4 <= len(cleaned) <= 160
                and cleaned not in {"企业资质", "资质等级", "企业资质等级"}
            )
        if canonical_key == "project_name":
            return (
                4 <= len(cleaned) <= 160
                and not any(token in cleaned for token in ("项目名称", "采购项目名称", "招标项目名称"))
            )
        return True

    def decide(
        self,
        field: TemplateField,
        facts: list[EnterpriseFact],
    ) -> FillDecision:
        authoritative = [
            fact
            for fact in facts
            if (
                fact.canonical_key == field.canonical_key
                and fact.value.strip()
                and fact.source_type not in self.NON_AUTHORITATIVE_FACT_SOURCES
            )
        ]
        candidates = [
            fact for fact in authoritative
            if self.value_matches_field_type(field.canonical_key, fact.value)
        ]
        if not candidates:
            reference_only = any(
                fact.canonical_key == field.canonical_key
                and fact.value.strip()
                and fact.source_type in self.NON_AUTHORITATIVE_FACT_SOURCES
                for fact in facts
            )
            if authoritative:
                missing_reason = "匹配内容不符合字段类型，已拒绝自动回填。"
            elif reference_only:
                missing_reason = (
                    "历史案例仅可参考写法，不能作为企业事实自动回填；"
                    "请从已授权企业数据库补充并核验。"
                )
            else:
                missing_reason = "当前企业资料库不存在该信息，请补充后继续。"
            return FillDecision(
                field=field,
                value=None,
                source_type=None,
                source_reference=None,
                confidence=0.0,
                status=FillStatus.MISSING,
                reason=missing_reason,
            )

        distinct_values = {fact.value.strip() for fact in candidates}
        if len(distinct_values) > 1:
            return FillDecision(
                field=field,
                value=None,
                source_type=None,
                source_reference=None,
                confidence=max(fact.confidence for fact in candidates),
                status=FillStatus.REVIEW_REQUIRED,
                reason="企业资料库存在多个不同值，需要人工确认采用口径。",
            )

        candidate = max(
            candidates,
            key=lambda fact: (fact.verified, fact.confidence),
        )
        status = FillStatus.AUTO_FILL
        reason = "来源已核验，可以自动回填。"
        if not candidate.verified or candidate.confidence < 1.0:
            status = FillStatus.REVIEW_REQUIRED
            reason = "数据尚未完成权威核验，需要人工确认。"
        if candidate.sensitivity != DataSensitivity.NORMAL:
            status = FillStatus.REVIEW_REQUIRED
            reason = "该字段属于受控敏感数据，授权审核后方可回填。"
        if (
            candidate.source_type in self.EVIDENCE_REQUIRED_SOURCES
            and not candidate.evidence_location
        ):
            status = FillStatus.REVIEW_REQUIRED
            reason = "企业事实已匹配，但来源记录缺少页码、章节或附件位置，需要人工复核。"

        return FillDecision(
            field=field,
            value=candidate.value.strip(),
            source_type=candidate.source_type,
            source_reference=candidate.source_reference,
            confidence=candidate.confidence,
            status=status,
            reason=reason,
            evidence_title=candidate.evidence_title,
            evidence_excerpt=candidate.evidence_excerpt,
            evidence_location=candidate.evidence_location,
        )

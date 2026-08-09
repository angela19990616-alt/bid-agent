from __future__ import annotations

import re
from enum import StrEnum


class SemanticValueType(StrEnum):
    PROJECT_NAME = "project_name"
    PROJECT_IDENTIFIER = "project_identifier"
    ORGANIZATION_NAME = "organization_name"
    PERSON_NAME = "person_name"
    IDENTITY_NUMBER = "identity_number"
    JOB_TITLE = "job_title"
    DATE = "date"
    ADDRESS = "address"
    POSTAL_CODE = "postal_code"
    PHONE = "phone"
    WEBSITE = "website"
    QUALIFICATION = "qualification"
    BANK_ACCOUNT = "bank_account"
    BID_ROUND = "bid_round"
    FIELD_LABEL = "field_label"
    LABELED_TEXT = "labeled_text"
    DOCUMENT_REFERENCE = "document_reference"
    PERSON_REFERENCE = "person_reference"
    NARRATIVE_TEXT = "narrative_text"
    PLACEHOLDER = "placeholder"
    UNKNOWN = "unknown"


FIELD_EXPECTATIONS: dict[str, tuple[SemanticValueType, str]] = {
    "project_name": (SemanticValueType.PROJECT_NAME, "项目名称"),
    "project_number": (SemanticValueType.PROJECT_IDENTIFIER, "项目编号"),
    "bidder_name": (SemanticValueType.ORGANIZATION_NAME, "企业名称"),
    "legal_representative": (SemanticValueType.PERSON_NAME, "姓名"),
    "authorized_representative": (SemanticValueType.PERSON_NAME, "姓名"),
    "contact_person": (SemanticValueType.PERSON_NAME, "姓名"),
    "project_manager_name": (SemanticValueType.PERSON_NAME, "姓名"),
    "technical_lead_name": (SemanticValueType.PERSON_NAME, "姓名"),
    "signatory_name": (SemanticValueType.PERSON_NAME, "姓名"),
    "person_id_number": (SemanticValueType.IDENTITY_NUMBER, "身份证号码"),
    "person_title": (SemanticValueType.JOB_TITLE, "职务"),
    "date": (SemanticValueType.DATE, "日期"),
    "registered_address": (SemanticValueType.ADDRESS, "地址"),
    "postal_code": (SemanticValueType.POSTAL_CODE, "邮政编码"),
    "contact_phone": (SemanticValueType.PHONE, "电话号码"),
    "fax": (SemanticValueType.PHONE, "传真号码"),
    "website": (SemanticValueType.WEBSITE, "网址"),
    "enterprise_qualification": (SemanticValueType.QUALIFICATION, "资质信息"),
    "bank_account": (SemanticValueType.BANK_ACCOUNT, "银行账号"),
    "bid_round": (SemanticValueType.BID_ROUND, "报价轮次"),
}


class FieldSemanticClassifier:
    """Classify a candidate value before comparing it with a template field.

    Extraction rules may find nearby text, but they do not decide whether that
    text is usable.  This classifier gives both sides a stable semantic type;
    strict fill accepts a value only when its type matches the field contract.
    """

    FIELD_LABELS = {
        "项目名称", "采购项目名称", "招标项目名称", "项目编号",
        "采购编号", "招标编号", "供应商名称", "投标人名称",
        "响应人名称", "企业名称", "单位名称", "法定代表人",
        "授权代表", "委托代理人", "联系人", "姓名", "联系电话",
        "手机", "电话", "传真", "网址", "注册地址", "邮政编码",
        "银行账号", "账号", "资质等级", "企业资质",
    }
    PLACEHOLDER_PATTERN = re.compile(
        r"^(?:[xXＸｘ_＿·…\-.]{2,}|"
        r"请?(?:填写|补充)|待(?:定|填写|补充)|不适用|年月日)$"
    )
    DOCUMENT_PATTERN = re.compile(
        r"(?:身份证明(?:书)?|(?:授权)?委托书(?:等)?|身份证|营业执照|"
        r"证明书|复印件|扫描件|附件|公章|盖章)"
    )
    PERSON_REFERENCE_PATTERN = re.compile(r"^[\u4e00-\u9fff·]{1,12}(?:先生|女士|老师)$")
    NARRATIVE_PATTERN = re.compile(
        r"(?:指导下|委托人|转委托|负责|参加|名义|"
        r"材料|渠道查询|职务|签字|签名)"
    )

    @classmethod
    def expected_type(cls, canonical_key: str) -> SemanticValueType:
        return FIELD_EXPECTATIONS.get(
            canonical_key, (SemanticValueType.UNKNOWN, "文本")
        )[0]

    @classmethod
    def expected_label(cls, canonical_key: str) -> str:
        return FIELD_EXPECTATIONS.get(
            canonical_key, (SemanticValueType.UNKNOWN, "文本")
        )[1]

    @classmethod
    def matches(cls, canonical_key: str, value: str) -> bool:
        expected = cls.expected_type(canonical_key)
        if expected is SemanticValueType.UNKNOWN:
            return bool(str(value or "").strip())
        return cls.classify(value) is expected

    @classmethod
    def classify(cls, value: str) -> SemanticValueType:
        raw = str(value or "").strip()
        compact = re.sub(r"\s+", "", raw).strip(":：|_- ")
        if not compact:
            return SemanticValueType.UNKNOWN
        lowered = compact.lower()
        if cls.PLACEHOLDER_PATTERN.fullmatch(compact) or "xxx" in lowered:
            return SemanticValueType.PLACEHOLDER
        if compact in cls.FIELD_LABELS:
            return SemanticValueType.FIELD_LABEL
        if re.match(r"^[^:：]{1,20}[:：]", raw) and re.search(
            r"名称|全称|公章|姓名|电话|网址", raw.split(":", 1)[0].split("：", 1)[0]
        ):
            return SemanticValueType.LABELED_TEXT
        normalized_url = raw.rstrip(".,;:!?/()[]{}。，；：！？、（）")
        if re.fullmatch(
            r"(?:https?://|www\.)[A-Za-z0-9.-]+(?:\:[0-9]{1,5})?"
            r"(?:/[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]*)?",
            normalized_url,
            re.IGNORECASE,
        ):
            return SemanticValueType.WEBSITE
        if re.fullmatch(
            r"(?:20\d{2}[-/.](?:0?[1-9]|1[0-2])[-/.](?:0?[1-9]|[12]\d|3[01])|"
            r"20\d{2}年(?:0?[1-9]|1[0-2])月(?:0?[1-9]|[12]\d|3[01])日)",
            compact,
        ):
            return SemanticValueType.DATE
        if re.fullmatch(r"\d{17}[0-9Xx]", compact):
            return SemanticValueType.IDENTITY_NUMBER
        if re.fullmatch(r"(?:第)?[一二三四五六七八九十\d]+轮", compact):
            return SemanticValueType.BID_ROUND
        if re.fullmatch(r"\d{6}", compact):
            return SemanticValueType.POSTAL_CODE
        if re.fullmatch(
            r"(?:\+?86[- ]?)?(?:1\d{10}|0\d{2,3}[- ]?\d{7,8})", raw
        ):
            return SemanticValueType.PHONE
        if re.fullmatch(r"\d{8,30}", compact):
            return SemanticValueType.BANK_ACCOUNT
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{2,79}", compact):
            return SemanticValueType.PROJECT_IDENTIFIER
        if re.search(
            r"(?:公司|集团|事务所|研究院|研究所|中心|分公司|"
            r"合伙企业|协会|学会|委员会|大学|学院)$",
            compact,
        ):
            return SemanticValueType.ORGANIZATION_NAME
        if 6 <= len(compact) <= 120 and re.search(
            r"(?:省|市|区|县|乡|镇|街道|路|街|胡同|号|院|楼|层|室)",
            compact,
        ):
            return SemanticValueType.ADDRESS
        if 2 <= len(compact) <= 160 and re.search(
            r"(?:资质|证书|认证|许可|备案|注册会计师|"
            r"咨询工程师|法律职业资格|[^一-鿿](?:甲|乙|丙)级)",
            compact,
        ):
            return SemanticValueType.QUALIFICATION
        if cls.DOCUMENT_PATTERN.search(compact):
            return SemanticValueType.DOCUMENT_REFERENCE
        if cls.PERSON_REFERENCE_PATTERN.fullmatch(compact):
            return SemanticValueType.PERSON_REFERENCE
        if cls.NARRATIVE_PATTERN.search(compact):
            return SemanticValueType.NARRATIVE_TEXT
        if 2 <= len(compact) <= 24 and re.search(
            r"(?:经理|总监|主任|负责人|工程师|顾问|专员|助理|董事|监事)$",
            compact,
        ):
            return SemanticValueType.JOB_TITLE
        if 4 <= len(compact) <= 160 and re.search(
            r"(?:项目|工程|服务|采购|建设|咨询)", compact
        ):
            return SemanticValueType.PROJECT_NAME
        if re.fullmatch(r"[一-鿿]{2,4}", compact) or re.fullmatch(
            r"[一-鿿]{1,10}·[一-鿿·]{1,20}", compact
        ):
            return SemanticValueType.PERSON_NAME
        return SemanticValueType.UNKNOWN

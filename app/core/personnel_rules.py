from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.entity_resolution import Person, ProjectRole


@dataclass(frozen=True)
class PersonnelRule:
    role: ProjectRole
    required_certificates: tuple[str, ...] = ()
    minimum_experience_years: float | None = None
    require_active_employment: bool = True


@dataclass(frozen=True)
class PersonnelRuleResult:
    status: str
    eligible: bool
    checks: tuple[dict[str, Any], ...]
    reason: str

    def snapshot(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "eligible": self.eligible,
            "checks": list(self.checks),
            "reason": self.reason,
        }


class PersonnelEntityRuleEngine:
    """Evaluate verified Person history without guessing missing facts."""

    @staticmethod
    @lru_cache(maxsize=1)
    def configuration() -> dict[str, Any]:
        path = (
            Path(__file__).resolve().parents[2]
            / "config" / "rules" / "personnel_rules.default.json"
        )
        return json.loads(path.read_text(encoding="utf-8"))

    def evaluate(
        self,
        person: Person,
        rule: PersonnelRule,
        *,
        as_of: date | None = None,
    ) -> PersonnelRuleResult:
        today = as_of or date.today()
        checks: list[dict[str, Any]] = []
        if rule.require_active_employment:
            active = self._active_employment(person.employment_history, today)
            checks.append({
                "rule": "active_employment",
                "passed": active is True,
                "known": active is not None,
                "message": (
                    "当前劳动关系有效"
                    if active is True
                    else "人员劳动关系已失效"
                    if active is False
                    else "缺少当前劳动关系或所属单位核验记录"
                ),
            })

        available = self._valid_certificates(person, today)
        for required in rule.required_certificates:
            matched = any(required in item or item in required for item in available)
            checks.append({
                "rule": "required_certificate",
                "requirement": required,
                "passed": matched,
                "known": bool(available),
                "message": (
                    f"已核验有效证书：{required}"
                    if matched else f"未核验到有效证书：{required}"
                ),
            })

        if rule.minimum_experience_years is not None:
            years = self._experience_years(person.role_history, today)
            checks.append({
                "rule": "minimum_experience_years",
                "requirement": rule.minimum_experience_years,
                "actual": years,
                "passed": years is not None and years >= rule.minimum_experience_years,
                "known": years is not None,
                "message": (
                    f"已核验相关经历约 {years:.1f} 年"
                    if years is not None else "缺少可计算年限的角色履历"
                ),
            })

        failures = [item for item in checks if not item["passed"]]
        if not failures:
            return PersonnelRuleResult(
                status="AUTO_FILL",
                eligible=True,
                checks=tuple(checks),
                reason="人员实体和全部资格规则均已核验通过。",
            )
        return PersonnelRuleResult(
            status=str(
                self.configuration().get("defaults", {}).get(
                    "unmet_rule_status", "REVIEW_REQUIRED"
                )
            ),
            eligible=False,
            checks=tuple(checks),
            reason="存在未满足或缺少证据的人员资格条件，需要人工审核。",
        )

    @staticmethod
    def _active_employment(
        history: tuple[dict[str, Any], ...], today: date
    ) -> bool | None:
        if not history:
            return None
        known = False
        for item in history:
            status = str(item.get("status") or "").lower()
            start = PersonnelEntityRuleEngine._date(item.get("valid_from") or item.get("start_date"))
            end = PersonnelEntityRuleEngine._date(item.get("valid_to") or item.get("end_date"))
            if status in {"active", "employed", "在职"}:
                known = True
                if (start is None or start <= today) and (end is None or end >= today):
                    return True
            elif status in {"expired", "left", "terminated", "离职"}:
                known = True
        return False if known else None

    @staticmethod
    def _valid_certificates(person: Person, today: date) -> set[str]:
        result: set[str] = set()
        records = [*person.certificates, *person.certification_history]
        for item in records:
            name = str(item.get("type") or item.get("name") or "").strip()
            if not name:
                continue
            status = str(item.get("status") or "valid").lower()
            expires = PersonnelEntityRuleEngine._date(
                item.get("valid_to") or item.get("expires_at")
            )
            if status in {"expired", "revoked", "rejected", "失效", "注销"}:
                continue
            if expires is not None and expires < today:
                continue
            result.add(name)
        return result

    @staticmethod
    def _experience_years(
        history: tuple[dict[str, Any], ...], today: date
    ) -> float | None:
        if not history:
            return None
        days = 0
        known = False
        for item in history:
            direct = item.get("years")
            if isinstance(direct, (int, float)):
                days += int(float(direct) * 365.25)
                known = True
                continue
            start = PersonnelEntityRuleEngine._date(
                item.get("valid_from") or item.get("start_date")
            )
            end = PersonnelEntityRuleEngine._date(
                item.get("valid_to") or item.get("end_date")
            ) or today
            if start is not None and end >= start:
                days += (end - start).days
                known = True
        return round(days / 365.25, 2) if known else None

    @staticmethod
    def _date(value: Any) -> date | None:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value[:10])
            except ValueError:
                return None
        return None

from uuid import uuid4

from app.knowledge.enterprise_fact_resolver import EnterpriseFactResolver


def test_resolver_only_returns_verified_structured_enterprise_facts(
    monkeypatch,
):
    class Cursor:
        def execute(self, _sql, _params):
            return None

        def fetchall(self):
            return [
            {
                "category": "company_profile",
                "title": "企业工商信息",
                "metadata": {
                    "verified_enterprise_fact": True,
                    "enterprise_facts": {
                        "bidder_name": "北京大岳咨询有限责任公司"
                    },
                },
            },
            ]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    class Connection:
        def cursor(self, **_kwargs):
            return Cursor()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(
        "app.knowledge.enterprise_fact_resolver.connect", Connection
    )

    facts = EnterpriseFactResolver().resolve(uuid4())

    assert [(fact.canonical_key, fact.value) for fact in facts] == [
        ("bidder_name", "北京大岳咨询有限责任公司")
    ]

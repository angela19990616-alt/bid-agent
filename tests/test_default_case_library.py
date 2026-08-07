from app.knowledge.default_case_library import (
    default_case_library_summary,
    load_default_case_library,
)


def test_default_case_library_is_exactly_five_private_reference_cases():
    library = load_default_case_library()
    summary = default_case_library_summary()

    assert len(library["cases"]) == 5
    assert all(item["active"] for item in library["cases"])
    assert summary == {
        "count": 5,
        "scope": "organization_private",
        "fact_usage": "prohibited",
        "version": "1.0.0",
    }

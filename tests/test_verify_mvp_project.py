import pytest

import scripts.verify_mvp_project as verify_module


def test_verification_requires_explicit_mutation_flag(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        ["verify_mvp_project", "5c22a53b-44c6-47b6-a2a1-7c859e0a4fb4"],
    )
    with pytest.raises(SystemExit) as exc:
        verify_module.main()
    assert exc.value.code == 2

from app.services.requirement_service import RequirementService


def test_requirement_classification_and_importance():
    service = RequirementService()

    assert service._classify("评分标准：实施方案完整得 10 分") == "scoring"
    assert service._classify("投标人须提供相关资质证书") == "qualification"
    assert service._classify("成果应在十日内提交并验收") == "delivery"
    assert service._classify("系统应支持数据备份") == "technical"
    assert service._importance("投标文件不得包含虚假材料") == "high"


def test_short_noise_is_not_candidate():
    service = RequirementService()

    assert service._is_candidate("须知") is False
    assert service._is_candidate("本系统应支持完整的数据备份功能。") is True

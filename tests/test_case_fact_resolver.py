from app.knowledge.case_fact_resolver import CaseFactResolver


def test_extracts_review_candidates_with_readable_evidence():
    candidates = CaseFactResolver.extract([
        {
            "title": "案例1·中标响应文件",
            "content": "供应商名称：北京大岳咨询有限责任公司\n法定代表人：金永祥\n邮政编码：100032",
        },
        {
            "title": "案例2·中标响应文件",
            "content": "投标人名称：北京大岳咨询有限责任公司\n法定代表人：金永祥",
        },
    ])

    assert candidates["bidder_name"].value == "北京大岳咨询有限责任公司"
    assert candidates["bidder_name"].match_count == 2
    assert candidates["legal_representative"].value == "金永祥"
    assert "法定代表人" in candidates["legal_representative"].source_excerpt
    assert candidates["legal_representative"].source_location == "原文第 2 段"


def test_rejects_placeholders():
    candidates = CaseFactResolver.extract([
        {"title": "模板", "content": "供应商名称：XXXX有限公司\n法定代表人：填写"},
    ])
    assert "bidder_name" not in candidates
    assert "legal_representative" not in candidates


def test_rejects_person_field_label_as_a_case_candidate():
    candidates = CaseFactResolver.extract([
        {
            "title": "响应格式模板",
            "content": "法定代表人：法人或授权代表",
        }
    ])

    assert "legal_representative" not in candidates


def test_evidence_location_includes_nearest_chapter_and_paragraph():
    candidates = CaseFactResolver.extract([{
        "title": "案例一·中标响应文件.docx",
        "content": "第三章 投标人基本情况\n一、企业信息\n供应商名称：北京大岳咨询有限责任公司",
    }])

    assert candidates["bidder_name"].source_title.endswith(".docx")
    assert "章节「一、企业信息」" in candidates["bidder_name"].source_location
    assert "第 3 段" in candidates["bidder_name"].source_location

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


def test_rejects_prose_and_document_names_from_person_fields():
    candidates = CaseFactResolver.extract([{
        "title": "历史响应文件",
        "content": (
            "法定代表人身份证明书\n"
            "在专家授权和指导下，完成项目。\n"
            "授权委托书等材料应加盖公章。\n"
            "联系人：电话"
        ),
    }])

    assert "legal_representative" not in candidates
    assert "authorized_representative" not in candidates
    assert "contact_person" not in candidates


def test_company_and_website_patterns_stop_at_field_value():
    candidates = CaseFactResolver.extract([{
        "title": "历史响应文件",
        "content": (
            "投标人全称（公章）：北京大岳咨询有限责任公司\n"
            "网址：www.example.com）等渠道查询"
        ),
    }])

    assert candidates["bidder_name"].value == "北京大岳咨询有限责任公司"
    assert candidates["website"].value == "www.example.com"

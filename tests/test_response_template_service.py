from io import BytesIO
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

from app.services.response_template_service import ResponseTemplateService


def _template_bytes(*, embedded: bool = True) -> bytes:
    document = Document()
    if embedded:
        document.add_heading("采购需求", level=1)
        document.add_paragraph("此处是采购文件正文，不应进入响应文件。")
    document.add_heading("附件：响应文件格式", level=1)
    document.add_paragraph("投标人必须严格按照本格式填写，不得修改表格。")
    table = document.add_table(rows=2, cols=2)
    table.style = "Table Grid"
    table.cell(0, 0).text = "项目名称"
    table.cell(0, 1).text = "{{project_name}}"
    table.cell(1, 0).text = "供应商名称"
    table.cell(1, 1).text = ""
    document.add_heading("技术方案", level=1)
    document.add_paragraph("请在此处填写。")
    stream = BytesIO()
    document.save(stream)
    return stream.getvalue()


def test_detects_embedded_docx_template_and_strict_rules():
    descriptor = ResponseTemplateService().detect(
        "招标文件.docx", _template_bytes()
    )

    assert descriptor.detected is True
    assert descriptor.template_kind == "embedded_response_section"
    assert descriptor.fidelity == "exact_template"
    assert descriptor.start_block is not None
    assert "project_name" in descriptor.placeholders
    assert "严格按照" in descriptor.strict_reasons


def test_extracts_response_template_outline_up_to_five_levels():
    document = Document()
    document.add_heading("采购需求", level=1)
    document.add_heading("附件：投标文件格式", level=1)
    document.add_heading("一、投标函", level=1)
    document.add_heading("（一）项目基本信息", level=2)
    document.add_heading("1.1 报价信息", level=3)
    document.add_heading("1.1.1 报价明细", level=4)
    document.add_heading("1.1.1.1 其他说明", level=5)
    document.add_heading(
        "一、本段是很长的说明文字，不应当作为可编辑目录标题展示给用户，而应当保留在原模板正文中。",
        level=1,
    )
    document.add_heading("第八章 评审办法", level=1)
    document.add_heading("一、评审原则", level=1)
    stream = BytesIO()
    document.save(stream)

    descriptor = ResponseTemplateService().detect(
        "招标文件.docx", stream.getvalue()
    )

    assert [item["title"] for item in descriptor.outline] == [
        "附件：投标文件格式",
        "一、投标函",
        "（一）项目基本信息",
        "1.1 报价信息",
        "1.1.1 报价明细",
        "1.1.1.1 其他说明",
    ]
    assert [item["level"] for item in descriptor.outline] == [1, 1, 2, 3, 4, 5]


def test_repeated_response_format_title_prefers_later_real_chapter():
    document = Document()
    document.add_paragraph("第六章 响应文件格式")
    document.add_heading("三、响应文件的编制", level=1)
    document.add_paragraph(
        "说明：本部分格式用于询问函，不属于响应文件格式的组成部分。"
    )
    document.add_heading("第五章 合同条款", level=1)
    document.add_paragraph("第六章  响应文件格式")
    document.add_heading("一、响应函", level=1)
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "供应商名称"
    table.cell(0, 1).text = ""
    stream = BytesIO()
    document.save(stream)

    descriptor = ResponseTemplateService().detect(
        "采购文件.docx", stream.getvalue()
    )

    assert descriptor.marker_text == "第六章  响应文件格式"
    assert [item["title"] for item in descriptor.outline] == [
        "第六章 响应文件格式",
        "一、响应函",
    ]
    assert any(
        item["field_key"] == "bidder_name"
        for item in descriptor.fields
    )


def test_fills_verified_values_and_keeps_original_table(tmp_path):
    service = ResponseTemplateService()
    content = _template_bytes()
    descriptor = service.detect("招标文件.docx", content)
    output = tmp_path / "filled.docx"

    report = service.fill_docx(
        template_content=content,
        output_path=output,
        descriptor=descriptor,
        field_values={
            "project_name": "测试采购项目",
            "bidder_name": "已核验供应商",
        },
        sections=[{"title": "实施计划", "content": "分三个阶段实施。"}],
    )

    result = Document(output)
    full_text = "\n".join(
        [item.text for item in result.paragraphs]
        + [cell.text for table in result.tables for row in table.rows for cell in row.cells]
    )
    assert "采购文件正文" not in full_text
    assert "测试采购项目" in full_text
    assert "已核验供应商" in full_text
    assert "分三个阶段实施" in full_text
    assert len(result.tables) == 1
    assert report.unresolved_sections == ()


def test_missing_template_value_is_not_invented(tmp_path):
    service = ResponseTemplateService()
    content = _template_bytes(embedded=False)
    descriptor = service.detect("响应文件格式模板.docx", content)
    output = tmp_path / "filled.docx"

    report = service.fill_docx(
        template_content=content,
        output_path=output,
        descriptor=descriptor,
        field_values={},
        sections=[],
    )

    assert "project_name" in report.unresolved_fields
    assert "{{project_name}}" in "\n".join(
        cell.text
        for table in Document(output).tables
        for row in table.rows
        for cell in row.cells
    )


def test_pdf_template_is_not_falsely_claimed_as_auto_fillable():
    descriptor = ResponseTemplateService().detect(
        "附件-投标文件格式.pdf", b"%PDF-1.7"
    )

    assert descriptor.detected is True
    assert descriptor.fidelity == "manual_exact_fill_required"


def test_extracts_project_number_from_procurement_source_only():
    document = Document()
    document.add_paragraph("项目编号：SCXHR20250320。")
    document.add_paragraph("供应商名称：此处不得从历史响应文件推断")
    stream = BytesIO()
    document.save(stream)

    values = ResponseTemplateService().extract_source_fields(
        "招标文件.docx", stream.getvalue()
    )

    assert values == {"project_number": "SCXHR20250320"}


def test_empty_paragraph_is_never_selected_as_section_heading(tmp_path):
    document = Document()
    document.add_paragraph("")
    document.add_heading("附件：响应文件格式", level=1)
    document.add_paragraph("")
    document.add_heading("技术方案", level=1)
    stream = BytesIO()
    document.save(stream)
    content = stream.getvalue()
    service = ResponseTemplateService()
    descriptor = service.detect("响应文件格式.docx", content)

    report = service.fill_docx(
        template_content=content,
        output_path=tmp_path / "filled.docx",
        descriptor=descriptor,
        field_values={},
        sections=[{"title": "技术方案", "content": "应写在本标题后。"}],
    )

    paragraphs = [item.text for item in Document(tmp_path / "filled.docx").paragraphs]
    heading_index = paragraphs.index("技术方案")
    content_index = paragraphs.index("应写在本标题后。")
    assert content_index == heading_index + 1
    assert report.unresolved_sections == ()


def test_technical_solution_does_not_match_short_table_label():
    document = Document()
    table = document.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "技术"
    expected = document.add_paragraph("5.格式13 项目实施方案")

    target = ResponseTemplateService._find_heading(document, "技术方案")

    assert target is not None
    assert target._p is expected._p


def test_form_control_prefix_is_hidden_from_user_facing_outline():
    assert ResponseTemplateService._display_heading(
        "5.格式13 项目实施方案"
    ) == "项目实施方案"


def test_inserted_content_does_not_inherit_heading_page_break():
    document = Document()
    anchor = document.add_paragraph("项目实施方案")
    anchor.paragraph_format.page_break_before = True

    ResponseTemplateService._insert_content_after(anchor, "1. 工作范围\n正文内容")

    stream = BytesIO()
    document.save(stream)
    result = Document(BytesIO(stream.getvalue()))
    heading, body = result.paragraphs[1:3]
    assert heading.paragraph_format.page_break_before is not True
    assert body.paragraph_format.page_break_before is not True
    assert heading.runs[0].bold is True
    assert body.runs[0].font.color.rgb == RGBColor(0, 0, 0)


def test_detects_template_fonts_and_uses_them_for_inserted_content(tmp_path):
    document = Document()
    document.add_heading("附件：响应文件格式", level=1)
    heading = document.add_heading("技术方案", level=1)
    heading_run = heading.runs[0]
    heading_run.font.name = "黑体"
    heading_run._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")
    body = document.add_paragraph("正文样式参考")
    body_run = body.runs[0]
    body_run.font.name = "仿宋_GB2312"
    body_run._element.rPr.rFonts.set(qn("w:eastAsia"), "仿宋_GB2312")
    body_run.font.size = Pt(16)
    stream = BytesIO()
    document.save(stream)
    content = stream.getvalue()
    service = ResponseTemplateService()
    descriptor = service.detect("投标文件格式.docx", content)

    assert "仿宋_GB2312" in descriptor.font_profile["detected_fonts"]
    assert "黑体" in descriptor.font_profile["detected_fonts"]

    output = tmp_path / "font-preserved.docx"
    service.fill_docx(
        template_content=content,
        output_path=output,
        descriptor=descriptor,
        field_values={},
        sections=[{"title": "技术方案", "content": "一、实施思路\n这是新生成的正文。"}],
    )
    result = Document(output)
    generated_body = next(
        item for item in result.paragraphs if item.text == "这是新生成的正文。"
    )
    fonts = generated_body.runs[0]._element.rPr.rFonts
    assert fonts.get(qn("w:eastAsia")) == "仿宋_GB2312"
    assert generated_body.runs[0].font.size.pt == 16


def test_table_fill_preserves_existing_target_font():
    document = Document()
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "供应商名称"
    target = table.cell(0, 1)
    run = target.paragraphs[0].add_run("{{bidder_name}}")
    run.font.name = "仿宋_GB2312"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "仿宋_GB2312")

    ResponseTemplateService._set_cell_text_preserving_style(
        target, "已核验企业"
    )

    assert target.text == "已核验企业"
    assert target.paragraphs[0].runs[0]._element.rPr.rFonts.get(
        qn("w:eastAsia")
    ) == "仿宋_GB2312"


def test_fills_visible_blank_label_paragraphs():
    document = Document()
    document.add_paragraph("项目编号： __________")
    document.add_paragraph("项目名称：")
    document.add_paragraph("供应商（加盖公章）：      ")
    filled: set[str] = set()

    ResponseTemplateService._fill_label_paragraphs(
        document,
        {
            "project_number": "SCXHR20250320",
            "project_name": "自贡智慧文旅项目",
            "bidder_name": "【待人工确认供应商名称】",
        },
        filled,
    )

    assert document.paragraphs[0].text == "项目编号： SCXHR20250320"
    assert document.paragraphs[1].text == "项目名称： 自贡智慧文旅项目"
    assert "【待人工确认供应商名称】" in document.paragraphs[2].text
    assert filled == {"project_number", "project_name", "bidder_name"}


def test_detects_and_fills_generic_blank_table_field(tmp_path):
    document = Document()
    document.add_heading("第七章 响应文件格式", level=1)
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "投标报价金额"
    table.cell(0, 1).text = ""
    stream = BytesIO()
    document.save(stream)
    content = stream.getvalue()
    service = ResponseTemplateService()
    descriptor = service.detect("招标文件.docx", content)
    field = next(
        item for item in descriptor.fields
        if item["label"] == "投标报价金额"
    )

    assert field["expected_source"] == "pricing_database"
    assert field["field_key"].startswith("custom_")

    output = tmp_path / "generic-fill.docx"
    report = service.fill_docx(
        template_content=content,
        output_path=output,
        descriptor=descriptor,
        field_values={field["field_key"]: "100000.00元"},
        sections=[],
    )

    result = Document(output)
    assert result.tables[0].cell(0, 1).text == "100000.00元"
    assert field["field_key"] in report.filled_fields


def test_detects_and_fills_generic_blank_paragraph_field(tmp_path):
    document = Document()
    document.add_heading("第七章 响应文件格式", level=1)
    document.add_paragraph("开户行： __________")
    document.add_heading("第八章 合同条款", level=1)
    document.add_paragraph("合同编号： __________")
    stream = BytesIO()
    document.save(stream)
    content = stream.getvalue()
    service = ResponseTemplateService()
    descriptor = service.detect("招标文件.docx", content)
    field = next(item for item in descriptor.fields if item["label"] == "开户行")

    assert all(item["label"] != "合同编号" for item in descriptor.fields)

    output = tmp_path / "paragraph-fill.docx"
    service.fill_docx(
        template_content=content,
        output_path=output,
        descriptor=descriptor,
        field_values={field["field_key"]: "中国银行自贡分行"},
        sections=[],
    )

    result = Document(output)
    assert result.paragraphs[-1].text == "开户行： 中国银行自贡分行"


def test_repository_tender_uses_actual_template_chapter_not_toc(tmp_path):
    samples = list(Path("database/输入（招标文件）").glob("*.docx"))
    if not samples:
        return
    service = ResponseTemplateService()
    content = samples[0].read_bytes()
    descriptor = service.detect(samples[0].name, content)

    assert descriptor.detected is True
    assert descriptor.start_block is not None
    assert descriptor.start_block > 300
    assert descriptor.marker_text.startswith("第七章")
    required = service.required_fields(descriptor.snapshot())
    assert {"project_name", "project_number", "bidder_name"} <= set(required)
    assert "legal_representative" in required
    assert len(required) >= 10
    assert descriptor.end_block is not None
    assert descriptor.end_block > descriptor.start_block

    report = service.fill_docx(
        template_content=content,
        output_path=tmp_path / "real-template-fill.docx",
        descriptor=descriptor,
        field_values={"project_name": "当前项目"},
        sections=[{"title": "技术方案", "content": "受控测试正文。"}],
    )
    assert report.unresolved_sections == ()
    result = Document(tmp_path / "real-template-fill.docx")
    implementation = next(
        item for item in result.paragraphs if "项目实施方案" in item.text
    )
    assert implementation._p.getnext() is not None
    assert "受控测试正文" in "".join(
        node.text or "" for node in implementation._p.getnext().iter()
    )

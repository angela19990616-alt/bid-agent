from docx import Document

from app.services.docx_builder import build_proposal_docx


def test_build_proposal_docx_with_response_matrix(tmp_path):
    output = tmp_path / "proposal.docx"

    build_proposal_docx(
        output,
        project_name="测试项目",
        section_title="实施方案",
        content="# 总体思路\n\n系统采用分阶段实施。\n\n- 每日备份",
        requirements=[
            {
                "normalized_text": "系统须支持每日备份。",
                "quote": "系统须支持每日备份。",
                "sources": [
                    {
                        "filename": "招标文件.pdf",
                        "locator": {
                            "kind": "page",
                            "page": 12,
                            "paragraph_start": None,
                            "paragraph_end": None,
                        },
                    }
                ],
            }
        ],
    )

    assert output.is_file()
    document = Document(output)
    text = "\n".join(item.text for item in document.paragraphs)
    assert "实施方案" in text
    assert "总体思路" in text
    assert len(document.tables) == 1
    assert document.tables[0].cell(1, 2).text.startswith(
        "招标文件.pdf，第 12 页"
    )

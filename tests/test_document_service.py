from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from app.services.document_service import (
    UnsupportedDocumentError,
    extract_text,
    split_text,
)


def test_extract_utf8_text():
    assert extract_text("需求.txt", "第一章\n第二章".encode()) == "第一章\n第二章"


def test_extract_docx():
    buffer = BytesIO()
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p><w:r><w:t>项目背景</w:t></w:r></w:p>
        <w:p><w:r><w:t>服务范围</w:t></w:r></w:p>
      </w:body>
    </w:document>
    """
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", xml)

    assert extract_text("招标文件.docx", buffer.getvalue()) == "项目背景\n服务范围"


def test_rejects_unsupported_file():
    with pytest.raises(UnsupportedDocumentError):
        extract_text("data.xlsx", b"content")


def test_split_text_preserves_content_with_overlap():
    chunks = split_text("第一段内容\n第二段内容\n第三段内容", chunk_size=12, overlap=3)

    assert len(chunks) >= 2
    assert "第一段内容" in chunks[0]
    assert "第三段内容" in chunks[-1]

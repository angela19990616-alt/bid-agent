from io import BytesIO

from docx import Document
import pymupdf

from app.services.pdf_template_conversion_service import (
    PdfTemplateConversionService,
)


def _pdf_bytes(*lines: str) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    point = pymupdf.Point(72, 72)
    for line in lines:
        page.insert_text(point, line)
        point.y += 24
    content = document.tobytes()
    document.close()
    return content


def test_real_pdf_is_converted_to_editable_docx():
    result = PdfTemplateConversionService(timeout_seconds=120).convert(
        _pdf_bytes(
            "BID RESPONSE FORM",
            "Bidder Name: ____________________",
            "Project Number: TEST-2026-001",
        )
    )

    assert result.status == "succeeded"
    assert result.content is not None
    assert result.page_count == 1
    assert result.paragraph_count > 0 or result.table_count > 0

    converted = Document(BytesIO(result.content))
    assert any(paragraph.text.strip() for paragraph in converted.paragraphs)


def test_malformed_pdf_stops_before_writer_selection():
    result = PdfTemplateConversionService().convert(b"not-a-pdf")

    assert result.status == "failed"
    assert result.content is None
    assert result.page_count == 0

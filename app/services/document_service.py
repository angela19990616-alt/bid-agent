from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from pypdf import PdfReader


class UnsupportedDocumentError(ValueError):
    pass


class EmptyDocumentError(ValueError):
    pass


class EncryptedDocumentError(ValueError):
    pass


@dataclass(frozen=True)
class SourceSegment:
    text: str
    locator_kind: str
    page_no: int | None = None
    paragraph_start: int | None = None
    paragraph_end: int | None = None


SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}
MVP_EXTENSIONS = {".pdf", ".docx"}


def parse_document(filename: str, content: bytes) -> list[SourceSegment]:
    extension = Path(filename).suffix.lower()
    if extension not in MVP_EXTENSIONS:
        supported = ", ".join(sorted(MVP_EXTENSIONS))
        raise UnsupportedDocumentError(
            f"不支持 {extension or '无扩展名'} 文件，支持：{supported}"
        )
    if not content:
        raise EmptyDocumentError("文件为空")
    if extension == ".pdf" and not content.lstrip().startswith(b"%PDF-"):
        raise UnsupportedDocumentError("文件内容不是有效 PDF")
    if extension == ".docx" and not content.startswith(b"PK"):
        raise UnsupportedDocumentError("文件内容不是有效 DOCX")
    if extension == ".pdf":
        return _parse_pdf(content)
    return _parse_docx(content)


def extract_text(filename: str, content: bytes) -> str:
    extension = Path(filename).suffix.lower()

    if extension not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise UnsupportedDocumentError(
            f"不支持 {extension or '无扩展名'} 文件，支持：{supported}"
        )

    if extension in {".txt", ".md"}:
        text = _decode_text(content)
    elif extension == ".pdf":
        reader = PdfReader(BytesIO(content))
        text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
    else:
        text = _extract_docx(content)

    normalized = "\n".join(
        line.strip() for line in text.splitlines() if line.strip()
    )
    if not normalized:
        raise EmptyDocumentError("文件中没有提取到可索引文字")
    return normalized


def split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    if chunk_size <= 0:
        raise ValueError("chunk_size 必须大于 0")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap 必须大于等于 0 且小于 chunk_size")

    paragraphs = [item.strip() for item in text.split("\n") if item.strip()]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        if len(paragraph) > chunk_size:
            if current:
                chunks.append(current)
                current = ""
            start = 0
            while start < len(paragraph):
                chunks.append(paragraph[start : start + chunk_size])
                start += chunk_size - overlap
            continue

        candidate = f"{current}\n{paragraph}".strip()
        if len(candidate) <= chunk_size:
            current = candidate
            continue

        chunks.append(current)
        prefix = current[-overlap:] if overlap else ""
        current = f"{prefix}\n{paragraph}".strip()

    if current:
        chunks.append(current)

    return [chunk for chunk in chunks if chunk]


def _decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise UnsupportedDocumentError("文本文件编码无法识别，请使用 UTF-8 或 GB18030")


def _extract_docx(content: bytes) -> str:
    return "\n".join(segment.text for segment in _parse_docx(content))


def _parse_pdf(content: bytes) -> list[SourceSegment]:
    try:
        reader = PdfReader(BytesIO(content))
    except Exception as exc:
        raise UnsupportedDocumentError("PDF 文件结构无效或已损坏") from exc
    if reader.is_encrypted:
        raise EncryptedDocumentError("PDF 已加密，请上传未加密文件")

    segments: list[SourceSegment] = []
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            value = page.extract_text() or ""
        except Exception as exc:
            raise UnsupportedDocumentError(
                f"PDF 第 {page_number} 页无法解析"
            ) from exc
        normalized = _normalize_text(value)
        if normalized:
            segments.append(
                SourceSegment(
                    text=normalized,
                    locator_kind="page",
                    page_no=page_number,
                )
            )
    if not segments:
        raise EmptyDocumentError(
            "PDF 中没有可检索文字，可能是扫描件，请上传可检索版本"
        )
    return segments


def _parse_docx(content: bytes) -> list[SourceSegment]:
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    try:
        with ZipFile(BytesIO(content)) as archive:
            xml = archive.read("word/document.xml")
    except (BadZipFile, KeyError) as exc:
        raise UnsupportedDocumentError("DOCX 文件结构无效或已损坏") from exc

    if len(xml) > 50 * 1024 * 1024:
        raise UnsupportedDocumentError("DOCX 文档正文过大")
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise UnsupportedDocumentError("DOCX 正文结构无效") from exc
    segments: list[SourceSegment] = []
    paragraph_index = 0

    def paragraph_text(paragraph) -> str:
        return "".join(
            node.text or "" for node in paragraph.iter(f"{namespace}t")
        ).strip()

    def append_paragraph(paragraph) -> tuple[int, str]:
        nonlocal paragraph_index
        paragraph_index += 1
        value = paragraph_text(paragraph)
        if value:
            segments.append(
                SourceSegment(
                    text=value,
                    locator_kind="paragraph",
                    paragraph_start=paragraph_index,
                    paragraph_end=paragraph_index,
                )
            )
        return paragraph_index, value

    body = root.find(f"{namespace}body")
    if body is None:
        raise EmptyDocumentError("DOCX 中没有正文")
    for child in body:
        if child.tag == f"{namespace}p":
            append_paragraph(child)
            continue
        if child.tag != f"{namespace}tbl":
            continue
        for row in child.findall(f"{namespace}tr"):
            row_start = paragraph_index + 1
            cells: list[str] = []
            for cell in row.findall(f"{namespace}tc"):
                values: list[str] = []
                for paragraph in cell.iter(f"{namespace}p"):
                    _, value = append_paragraph(paragraph)
                    if value:
                        values.append(value)
                cell_text = "；".join(values).strip()
                if cell_text:
                    cells.append(cell_text)
            if len(cells) >= 2:
                segments.append(
                    SourceSegment(
                        text=" | ".join(cells),
                        locator_kind="paragraph",
                        paragraph_start=row_start,
                        paragraph_end=paragraph_index,
                    )
                )
    if not segments:
        raise EmptyDocumentError("DOCX 中没有可检索文字")
    return segments


def _normalize_text(value: str) -> str:
    return "\n".join(
        line.strip() for line in value.splitlines() if line.strip()
    )

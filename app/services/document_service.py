from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from pypdf import PdfReader


class UnsupportedDocumentError(ValueError):
    pass


class EmptyDocumentError(ValueError):
    pass


SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}


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
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    try:
        with ZipFile(BytesIO(content)) as archive:
            xml = archive.read("word/document.xml")
    except (BadZipFile, KeyError) as exc:
        raise UnsupportedDocumentError("DOCX 文件结构无效或已损坏") from exc

    root = ElementTree.fromstring(xml)
    paragraphs: list[str] = []
    for paragraph in root.iter(f"{namespace}p"):
        value = "".join(
            node.text or "" for node in paragraph.iter(f"{namespace}t")
        ).strip()
        if value:
            paragraphs.append(value)
    return "\n".join(paragraphs)

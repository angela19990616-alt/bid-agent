from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from docx import Document
from docx.document import Document as DocumentType
from docx.oxml import OxmlElement
from docx.text.paragraph import Paragraph
from pypdf import PdfReader


TEMPLATE_MARKERS = (
    "投标文件格式", "响应文件格式", "报价文件格式", "资格响应格式",
    "技术响应格式", "附件格式", "响应文件组成及格式",
)
STRICT_MARKERS = (
    "不得修改", "不得增删", "格式不变", "严格按照", "按附件格式",
    "按本格式", "原格式",
)
FIELD_ALIASES = {
    "project_name": ("项目名称", "采购项目名称", "招标项目名称"),
    "project_number": ("项目编号", "采购编号", "招标编号"),
    "bidder_name": ("供应商名称", "投标人名称", "响应人名称"),
    "legal_representative": ("法定代表人",),
    "authorized_representative": ("授权代表", "委托代理人"),
    "date": ("日期", "响应日期", "投标日期"),
}
PLACEHOLDER_RE = re.compile(
    r"\{\{\s*([\w\u4e00-\u9fff.-]+)\s*\}\}"
    r"|\$\{\s*([\w\u4e00-\u9fff.-]+)\s*\}"
    r"|[\[\uff3b]\s*([\w\u4e00-\u9fff.-]+)\s*[\]\uff3d]"
)


@dataclass(frozen=True)
class TemplateDescriptor:
    detected: bool
    source_format: str
    template_kind: str
    fidelity: str
    confidence: float
    start_block: int | None
    marker_text: str | None
    table_count: int
    placeholders: tuple[str, ...]
    field_labels: tuple[str, ...]
    strict_reasons: tuple[str, ...]

    def snapshot(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TemplateFillReport:
    filled_fields: tuple[str, ...]
    unresolved_fields: tuple[str, ...]
    inserted_sections: tuple[str, ...]
    unresolved_sections: tuple[str, ...]

    def snapshot(self) -> dict[str, Any]:
        return asdict(self)


class ResponseTemplateService:
    """Detects and fills response templates without rebuilding their layout."""

    def detect(self, filename: str, content: bytes) -> TemplateDescriptor:
        suffix = Path(filename).suffix.lower()
        if suffix == ".docx":
            return self._detect_docx(filename, content)
        if suffix == ".pdf":
            marker_text = None
            try:
                reader = PdfReader(BytesIO(content))
                for page in reader.pages:
                    text = page.extract_text() or ""
                    marker_text = next(
                        (marker for marker in TEMPLATE_MARKERS if marker in text),
                        marker_text,
                    )
                    if marker_text:
                        break
            except Exception:
                # The parser/validator owns malformed-file reporting. Template
                # detection remains conservative and never claims coordinates.
                marker_text = None
            detected = bool(marker_text) or any(
                item in filename for item in TEMPLATE_MARKERS
            )
            return TemplateDescriptor(
                detected=detected,
                source_format="pdf",
                template_kind="pdf_reference",
                fidelity="manual_exact_fill_required",
                confidence=(0.8 if marker_text else 0.65 if detected else 0.0),
                start_block=None,
                marker_text=marker_text,
                table_count=0,
                placeholders=(),
                field_labels=(),
                strict_reasons=("PDF版式仅作为严格参照，不能猜测回填坐标。",),
            )
        return TemplateDescriptor(
            False, suffix.lstrip("."), "none", "planned", 0.0,
            None, None, 0, (), (), (),
        )

    @staticmethod
    def required_fields(descriptor: dict[str, Any]) -> list[str]:
        required = list(descriptor.get("placeholders") or ())
        labels = set(descriptor.get("field_labels") or ())
        for key, aliases in FIELD_ALIASES.items():
            if any(alias in labels for alias in aliases):
                required.append(key)
        return list(dict.fromkeys(required))

    def _detect_docx(self, filename: str, content: bytes) -> TemplateDescriptor:
        document = Document(BytesIO(content))
        blocks = list(document.element.body.iterchildren())
        texts = [self._block_text(block) for block in blocks]
        marker_candidates = [
            index for index, text in enumerate(texts)
            if any(marker in text for marker in TEMPLATE_MARKERS)
        ]
        # Tender tables of contents and explanatory paragraphs repeat the
        # title. Prefer the shortest heading-like occurrence, penalising TOC
        # fields and prose, instead of blindly taking the first/last match.
        marker_index = (
            min(
                marker_candidates,
                key=lambda index: (
                    0 if re.match(
                        r"^第[一二三四五六七八九十百\d]+章",
                        texts[index].replace(" ", ""),
                    ) else 1,
                    len(texts[index])
                    + (200 if "HYPERLINK" in texts[index] or "PAGEREF" in texts[index] else 0)
                    + (100 if "本章所制" in texts[index] else 0),
                    -index,
                ),
            )
            if marker_candidates else None
        )
        tables = len(document.tables)
        standalone = any(marker in filename for marker in TEMPLATE_MARKERS)
        detected = marker_index is not None or (standalone and tables > 0)
        start_block = 0 if standalone else marker_index
        candidate_text = "\n".join(
            texts[start_block:] if start_block is not None else []
        )
        placeholders = tuple(sorted({
            next(group for group in match.groups() if group)
            for match in PLACEHOLDER_RE.finditer(candidate_text)
        }))
        labels = self._fillable_labels(document)
        strict = tuple(marker for marker in STRICT_MARKERS if marker in candidate_text)
        confidence = 0.0
        if detected:
            confidence = min(
                0.99,
                0.55 + (0.15 if tables else 0) +
                (0.15 if placeholders or labels else 0) +
                (0.1 if strict else 0),
            )
        return TemplateDescriptor(
            detected=detected,
            source_format="docx",
            template_kind=(
                "standalone_attachment" if standalone
                else "embedded_response_section" if detected else "none"
            ),
            fidelity="exact_template" if detected else "planned",
            confidence=round(confidence, 3),
            start_block=start_block,
            marker_text=(texts[marker_index] if marker_index is not None else None),
            table_count=tables,
            placeholders=placeholders,
            field_labels=labels,
            strict_reasons=strict,
        )

    def fill_docx(
        self,
        *,
        template_content: bytes,
        output_path: Path,
        descriptor: TemplateDescriptor | dict[str, Any],
        field_values: dict[str, str],
        sections: list[dict[str, str]],
    ) -> TemplateFillReport:
        data = (
            descriptor.snapshot()
            if isinstance(descriptor, TemplateDescriptor)
            else descriptor
        )
        if not data.get("detected") or data.get("source_format") != "docx":
            raise ValueError("当前文件不是可自动回填的 DOCX 响应模板。")
        document = Document(BytesIO(template_content))
        start = data.get("start_block")
        if isinstance(start, int) and start > 0:
            self._retain_from_block(document, start)

        normalized_values = self._normalized_values(field_values)
        filled: set[str] = set()
        unresolved: set[str] = set()
        for paragraph in self._all_paragraphs(document):
            replaced, used, missing = self._replace_placeholders(
                paragraph.text, normalized_values
            )
            if replaced != paragraph.text:
                self._replace_paragraph_text(paragraph, replaced)
            filled.update(used)
            unresolved.update(missing)
        self._fill_label_cells(document, normalized_values, filled)
        descriptor_labels = set(data.get("field_labels") or ())
        for key, aliases in FIELD_ALIASES.items():
            if any(alias in descriptor_labels for alias in aliases):
                if key not in normalized_values:
                    unresolved.add(key)

        inserted: list[str] = []
        missing_sections: list[str] = []
        for section in sections:
            title = section["title"].strip()
            content = section.get("content", "").strip()
            target = self._find_heading(document, title)
            if target is None:
                missing_sections.append(title)
                continue
            self._insert_content_after(target, content)
            inserted.append(title)

        if missing_sections:
            generic_target = self._find_heading(document, "技术方案")
            if generic_target is not None:
                combined = "\n".join(
                    f"## {item['title']}\n{item.get('content', '')}"
                    for item in sections
                    if item["title"] in missing_sections
                )
                self._insert_content_after(generic_target, combined)
                inserted.extend(missing_sections)
                missing_sections = []

        output_path.parent.mkdir(parents=True, exist_ok=True)
        document.save(output_path)
        return TemplateFillReport(
            filled_fields=tuple(sorted(filled)),
            unresolved_fields=tuple(sorted(unresolved - filled)),
            inserted_sections=tuple(inserted),
            unresolved_sections=tuple(missing_sections),
        )

    @staticmethod
    def _block_text(block) -> str:
        return "".join(node.text or "" for node in block.iter()).strip()

    @staticmethod
    def _retain_from_block(document: DocumentType, start: int) -> None:
        body = document.element.body
        blocks = list(body.iterchildren())
        for block in blocks[:start]:
            if block.tag.endswith("}sectPr"):
                continue
            body.remove(block)

    @staticmethod
    def _all_paragraphs(document: DocumentType):
        yield from document.paragraphs
        for table in document.tables:
            for row in table.rows:
                for cell in row.cells:
                    yield from cell.paragraphs

    @staticmethod
    def _normalized_values(values: dict[str, str]) -> dict[str, str]:
        result = {
            key: str(value).strip()
            for key, value in values.items()
            if value is not None and str(value).strip()
        }
        for key, aliases in FIELD_ALIASES.items():
            if key not in result:
                continue
            for alias in aliases:
                result.setdefault(alias, result[key])
        return result

    @staticmethod
    def _replace_placeholders(
        text: str,
        values: dict[str, str],
    ) -> tuple[str, set[str], set[str]]:
        used: set[str] = set()
        missing: set[str] = set()

        def replace(match: re.Match) -> str:
            key = next(group for group in match.groups() if group).strip()
            value = values.get(key)
            if value is None:
                missing.add(key)
                return match.group(0)
            used.add(key)
            return value

        return PLACEHOLDER_RE.sub(replace, text), used, missing

    @staticmethod
    def _replace_paragraph_text(paragraph: Paragraph, value: str) -> None:
        if paragraph.runs:
            paragraph.runs[0].text = value
            for run in paragraph.runs[1:]:
                run.text = ""
        else:
            paragraph.add_run(value)

    @staticmethod
    def _fill_label_cells(
        document: DocumentType,
        values: dict[str, str],
        filled: set[str],
    ) -> None:
        for table in document.tables:
            for row in table.rows:
                for index, cell in enumerate(row.cells[:-1]):
                    label = re.sub(r"[\s:：()（）]", "", cell.text)
                    for key, aliases in FIELD_ALIASES.items():
                        if not any(re.sub(r"[\s:：()（）]", "", alias) in label for alias in aliases):
                            continue
                        value = values.get(key)
                        target = row.cells[index + 1]
                        if value and (not target.text.strip() or PLACEHOLDER_RE.search(target.text)):
                            target.text = value
                            filled.add(key)
                        break

    @staticmethod
    def _fillable_labels(document: DocumentType) -> tuple[str, ...]:
        labels: set[str] = set()
        for table in document.tables:
            for row in table.rows:
                for index, cell in enumerate(row.cells[:-1]):
                    label = re.sub(r"[\s:：()（）]", "", cell.text)
                    target = row.cells[index + 1].text.strip()
                    if target and not PLACEHOLDER_RE.search(target):
                        continue
                    for aliases in FIELD_ALIASES.values():
                        match = next(
                            (
                                alias for alias in aliases
                                if re.sub(r"[\s:：()（）]", "", alias)
                                in label
                            ),
                            None,
                        )
                        if match:
                            labels.add(match)
                            break
        return tuple(sorted(labels))

    @staticmethod
    def _find_heading(document: DocumentType, title: str) -> Paragraph | None:
        normalized = re.sub(r"[\s\d一二三四五六七八九十、.．()（）]", "", title)
        for paragraph in ResponseTemplateService._all_paragraphs(document):
            candidate = re.sub(
                r"[\s\d一二三四五六七八九十、.．()（）]", "", paragraph.text
            )
            if normalized and candidate and (
                normalized in candidate or candidate in normalized
            ):
                return paragraph
        return None

    @staticmethod
    def _insert_content_after(paragraph: Paragraph, content: str) -> None:
        anchor = paragraph._p
        for raw_line in reversed([line.strip() for line in content.splitlines() if line.strip()]):
            new_p = OxmlElement("w:p")
            if paragraph._p.pPr is not None:
                new_p.append(deepcopy(paragraph._p.pPr))
            run = OxmlElement("w:r")
            text = OxmlElement("w:t")
            text.text = re.sub(r"^#{1,6}\s*", "", raw_line)
            run.append(text)
            new_p.append(run)
            anchor.addnext(new_p)

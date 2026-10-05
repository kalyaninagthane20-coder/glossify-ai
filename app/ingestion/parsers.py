"""Turn uploaded files into ordered blocks that keep their structure.

Supported: .docx (headings, lists, tables), .pdf (paragraphs, heading heuristic),
.txt and .md (headings, bullet lists, paragraphs).

Each Block records what kind of element it came from, so the exporter can
rebuild the same structure in the translated file.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path


class UnsupportedFormatError(ValueError):
    pass


@dataclass
class Block:
    text: str
    block_type: str  # heading | paragraph | list_item | table_cell
    heading_level: int | None = None
    table_index: int | None = None
    row_index: int | None = None
    col_index: int | None = None
    page: int | None = None


def parse_document(filename: str, data: bytes) -> list[Block]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".docx":
        return parse_docx(BytesIO(data))
    if suffix == ".pdf":
        return parse_pdf(BytesIO(data))
    if suffix in (".txt", ".md"):
        return parse_text(data.decode("utf-8-sig"))
    raise UnsupportedFormatError(
        f"Unsupported file type '{suffix or 'none'}'. Use .docx, .pdf, .txt or .md."
    )


_HEADING_STYLE = re.compile(r"heading\s*(\d+)", re.IGNORECASE)


def parse_docx(fileobj) -> list[Block]:
    from docx import Document as DocxDocument
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = DocxDocument(fileobj)
    blocks: list[Block] = []
    table_index = 0

    # Walk the body in document order so paragraphs and tables stay interleaved correctly.
    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            paragraph = Paragraph(child, document)
            text = paragraph.text.strip()
            if not text:
                continue
            style = paragraph.style.name if paragraph.style is not None else ""
            match = _HEADING_STYLE.search(style)
            if match:
                blocks.append(Block(text, "heading", heading_level=int(match.group(1))))
            elif "list" in style.lower():
                blocks.append(Block(text, "list_item"))
            else:
                blocks.append(Block(text, "paragraph"))
        elif tag == "tbl":
            table = Table(child, document)
            for row_index, row in enumerate(table.rows):
                for col_index, cell in enumerate(row.cells):
                    text = cell.text.strip()
                    if text:
                        blocks.append(Block(text, "table_cell", table_index=table_index,
                                            row_index=row_index, col_index=col_index))
            table_index += 1
    return blocks


def parse_pdf(fileobj) -> list[Block]:
    from pypdf import PdfReader

    reader = PdfReader(fileobj)
    blocks: list[Block] = []
    for page_no, page in enumerate(reader.pages, start=1):
        raw = page.extract_text() or ""
        # Paragraphs are separated by blank lines in the extracted text.
        for chunk in re.split(r"\n\s*\n", raw):
            text = " ".join(chunk.split())
            if not text:
                continue
            if _looks_like_heading(text):
                blocks.append(Block(text, "heading", heading_level=2, page=page_no))
            else:
                blocks.append(Block(text, "paragraph", page=page_no))
    return blocks


def _looks_like_heading(text: str) -> bool:
    # Heuristic: short, Title Case and no sentence punctuation. PDFs have no real heading markup.
    return (len(text) <= 80 and len(text.split()) <= 10
            and not text.endswith((".", "!", "?", ":", ";")) and text.istitle())


def parse_text(text: str) -> list[Block]:
    blocks: list[Block] = []
    buffer: list[str] = []

    def flush():
        if buffer:
            blocks.append(Block(" ".join(buffer), "paragraph"))
            buffer.clear()

    for raw_line in text.replace("\r\n", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            flush()
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        bullet = re.match(r"^[-*]\s+(.*)$", line)
        if heading:
            flush()
            blocks.append(Block(heading.group(2).strip(), "heading", heading_level=len(heading.group(1))))
        elif bullet:
            flush()
            blocks.append(Block(bullet.group(1).strip(), "list_item"))
        else:
            buffer.append(line)
    flush()
    return [b for b in blocks if b.text]

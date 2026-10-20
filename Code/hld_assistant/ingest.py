"""Document loading and section-aware chunking.

Every chunk keeps (page, section) so answers can cite their source.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

HEADING_RE = re.compile(r"^(\d+(?:\.\d+){0,4})\.?\s+([A-Z][^\n]{2,120})$")


@dataclass
class Page:
    number: int
    text: str


@dataclass
class Chunk:
    page: int
    section: str  # e.g. "3.1 BrakeController (ApplicationSwComponentType)"
    text: str


def load_pages(name: str, data: bytes) -> list[Page]:
    suffix = Path(name).suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(data))
        pages = [Page(i + 1, p.extract_text() or "") for i, p in enumerate(reader.pages)]
        if not any(p.text.strip() for p in pages):
            raise ValueError(
                "No extractable text in PDF (scanned?). OCR is not enabled in this pilot; "
                "run OCR (e.g. ocrmypdf) first."
            )
        return pages
    if suffix == ".docx":
        return [Page(1, _docx_text(data))]
    if suffix in {".txt", ".md"}:
        text = data.decode("utf-8", errors="replace")
        if "\f" in text:  # form-feed = explicit page break
            return [Page(i + 1, t) for i, t in enumerate(text.split("\f"))]
        lines = text.splitlines()
        return [Page(i // 50 + 1, "\n".join(lines[i : i + 50])) for i in range(0, len(lines), 50)] or [Page(1, "")]
    raise ValueError(f"Unsupported file type: {suffix}")


def _docx_text(data: bytes) -> str:
    """Flatten a Word document; Heading styles get auto-numbers if the author did not number them."""
    from docx import Document

    doc, counters, lines = Document(BytesIO(data)), [0] * 5, []
    for block in doc.element.body.iterchildren():
        tag = block.tag.rsplit("}", 1)[-1]
        if tag == "p":
            from docx.text.paragraph import Paragraph

            para = Paragraph(block, doc)
            text, style = para.text.strip(), para.style.name or ""
            if not text:
                continue
            if style.startswith("Heading") and style[8:].strip().isdigit() and not HEADING_RE.match(text):
                level = min(int(style[8:]), 5)
                counters[level - 1] += 1
                counters[level:] = [0] * (5 - level)
                text = f"{'.'.join(str(n) for n in counters[:level])} {text}"
            lines.append(text)
        elif tag == "tbl":
            from docx.table import Table

            for row in Table(block, doc).rows:
                lines.append(" | ".join(c.text.strip() for c in row.cells))
    return "\n".join(lines)


def chunk_pages(pages: list[Page], max_chars: int = 1200) -> list[Chunk]:
    """Split by heading; oversize sections are split on line boundaries."""
    chunks: list[Chunk] = []
    state = {"section": "Preamble", "page": 1, "buf": []}

    def flush():
        body = "\n".join(state["buf"]).strip()
        state["buf"] = []
        if not body:
            return
        piece = ""
        for line in body.splitlines():
            if len(piece) + len(line) > max_chars and piece:
                chunks.append(Chunk(state["page"], state["section"], piece.strip()))
                piece = ""
            piece += line + "\n"
        if piece.strip():
            chunks.append(Chunk(state["page"], state["section"], piece.strip()))

    for page in pages:
        for line in page.text.splitlines():
            m = HEADING_RE.match(line.strip())
            if m:
                flush()
                state["section"] = f"{m.group(1)} {m.group(2).strip()}"
                state["page"] = page.number
            elif not state["buf"]:
                state["page"] = page.number
            state["buf"].append(line)
    flush()
    return chunks

"""
Conversion engine for TokenCraft — a thin wrapper over Microsoft's
open-source `markitdown` library. Framework-agnostic: takes raw bytes so it
can be called from FastAPI, a CLI, or anything else without depending on a
specific web framework's upload-file type.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from markitdown import MarkItDown


def convert_pdf_fast(tmp_path: str) -> str:
    """Fast PDF-to-text using PyMuPDF's raw text extraction instead of
    markitdown's pdfplumber-based table-aware extraction.

    ~20x faster in testing (178ms vs 3,838ms on a 20-page report), but it
    loses table structure — numbers and labels come out as flat lines in
    reading order rather than proper `| col | col |` Markdown tables. Only
    use this when raw text is enough and speed matters more than table
    fidelity. See README "Fast mode" section for guidance.
    """
    import fitz

    parts = []
    with fitz.open(tmp_path) as doc:
        for i, page in enumerate(doc, 1):
            text = page.get_text("text").strip()
            parts.append(f"<!-- page {i} -->\n\n{text}")
    return "\n\n".join(parts)


def get_converter(use_llm: bool = False, api_key: str = "") -> MarkItDown:
    """Build a MarkItDown instance. If `use_llm` is set and an API key is
    given, wires up OpenAI vision for reading scanned pages / images —
    otherwise falls back to the standard offline converters."""
    if use_llm and api_key:
        try:
            from openai import OpenAI

            client = OpenAI(api_key=api_key)
            return MarkItDown(llm_client=client, llm_model="gpt-4o")
        except ImportError:
            pass
    return MarkItDown()


def convert_bytes(
    filename: str, data: bytes, converter: MarkItDown, fast_pdf: bool = False
) -> tuple[str, str | None, str | None]:
    """Convert raw file bytes to Markdown.

    `fast_pdf=True` only changes behavior for .pdf files — it uses
    `convert_pdf_fast()` (PyMuPDF raw text) instead of markitdown's own PDF
    converter. Every other format is unaffected regardless of this flag.

    Returns (markdown_text, tmp_path, error). `tmp_path` is kept around
    (not deleted here) so callers can run further analysis on it (e.g. PDF
    page-image token estimation) before calling `cleanup_tmp`.
    """
    suffix = Path(filename).suffix
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        if fast_pdf and suffix.lower() == ".pdf":
            content = convert_pdf_fast(tmp_path)
        else:
            result = converter.convert(tmp_path)
            content = getattr(result, "markdown", None) or getattr(result, "text_content", "") or ""

        return content, tmp_path, None
    except Exception as e:
        if tmp_path:
            cleanup_tmp(tmp_path)
        return "", None, str(e)


def cleanup_tmp(tmp_path: str | None) -> None:
    if tmp_path and os.path.exists(tmp_path):
        try:
            os.remove(tmp_path)
        except OSError:
            pass

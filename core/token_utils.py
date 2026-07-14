"""
Token estimation utilities for TokenCraft.

Two distinct kinds of estimates live here:

1. Text tokens — how many tokens a string of text/Markdown costs. Uses
   tiktoken's cl100k_base vocabulary as a close proxy (Anthropic hasn't
   published Claude's exact tokenizer), falling back to a ~4-chars/token
   heuristic if tiktoken's vocab file can't be downloaded (e.g. no internet
   on first run, or a locked-down network).

2. Native-image tokens — how many tokens Claude spends per page/image when
   a PDF or image is sent as-is, based on Anthropic's documented formula:
       tokens ~= (width_px * height_px) / 750
   with the long edge first scaled down to 1568px, and a ~1600-token cap
   per tile. Source: docs.anthropic.com vision guide.

Everything here is a best-effort estimate for planning purposes, not an
exact billing count. The Anthropic API's token-counting endpoint is the
source of truth if you need precision.
"""

from __future__ import annotations

from dataclasses import dataclass

try:
    import tiktoken

    _ENC = tiktoken.get_encoding("cl100k_base")
except Exception:
    _ENC = None


def estimate_text_tokens(text: str) -> int:
    """Best-effort token count for a text/Markdown string."""
    if not text:
        return 0
    if _ENC is not None:
        try:
            return len(_ENC.encode(text))
        except Exception:
            pass
    # Fallback heuristic: ~4 characters per token for English-like text.
    return max(1, round(len(text) / 4))


# Anthropic's documented vision pixel-area formula.
CLAUDE_MAX_EDGE_PX = 1568
CLAUDE_PIXELS_PER_TOKEN = 750
CLAUDE_TOKEN_CAP_PER_IMAGE = 1600


def estimate_image_tokens(width_px: int, height_px: int) -> int:
    """Approximate Claude vision tokens for one image."""
    if width_px <= 0 or height_px <= 0:
        return 0
    long_edge = max(width_px, height_px)
    if long_edge > CLAUDE_MAX_EDGE_PX:
        scale = CLAUDE_MAX_EDGE_PX / long_edge
        width_px = int(width_px * scale)
        height_px = int(height_px * scale)
    tokens = int((width_px * height_px) / CLAUDE_PIXELS_PER_TOKEN)
    return min(tokens, CLAUDE_TOKEN_CAP_PER_IMAGE)


@dataclass
class PdfDensity:
    page_count: int
    image_count: int
    avg_text_chars_per_page: int
    image_heavy: bool
    label: str


@dataclass
class PdfAnalysis:
    density: "PdfDensity"
    image_tokens: int


def analyze_pdf(pdf_path: str, dpi: int = 150) -> PdfAnalysis:
    """Single-pass PDF analysis: opens the file once and computes both the
    image-density heuristic and the per-page image-token estimate together,
    instead of parsing the PDF twice (this used to be two separate
    functions, each opening the file — merged for speed, ~1.75x faster on
    a typical multi-page report)."""
    try:
        import fitz
    except ImportError:
        return PdfAnalysis(
            PdfDensity(0, 0, 0, False, "Unable to analyze (PyMuPDF not installed)"),
            0,
        )

    image_count = 0
    text_chars = 0
    image_tokens = 0
    with fitz.open(pdf_path) as doc:
        page_count = len(doc)
        for page in doc:
            image_count += len(page.get_images(full=True))
            text_chars += len(page.get_text("text"))
            rect = page.rect  # points, 1/72 inch
            width_px = int(rect.width * dpi / 72)
            height_px = int(rect.height * dpi / 72)
            image_tokens += estimate_image_tokens(width_px, height_px)

    avg_chars = round(text_chars / page_count) if page_count else 0
    image_heavy = page_count > 0 and (image_count >= page_count or avg_chars < 400)
    label = "Image-heavy — conversion recommended" if image_heavy else "Text-based — conversion optional"

    return PdfAnalysis(
        PdfDensity(page_count, image_count, avg_chars, image_heavy, label),
        image_tokens,
    )


def analyze_pdf_density(pdf_path: str) -> PdfDensity:
    """Kept for backwards compatibility / standalone use — prefer
    `analyze_pdf()` when you need both density and image tokens, since that
    does it in one pass instead of two."""
    return analyze_pdf(pdf_path).density


def estimate_pdf_page_image_tokens(pdf_path: str, dpi: int = 150) -> int:
    """Kept for backwards compatibility / standalone use — prefer
    `analyze_pdf()` when you need both density and image tokens."""
    return analyze_pdf(pdf_path, dpi=dpi).image_tokens


def get_image_dimensions(path_or_file) -> tuple[int, int] | None:
    """Return (width, height) for an image file, or None if unreadable."""
    try:
        from PIL import Image

        with Image.open(path_or_file) as img:
            return img.size
    except Exception:
        return None


@dataclass
class SavingsResult:
    native_tokens: int
    converted_tokens: int
    multiplier: float
    pct_saved: float
    verdict: str
    applicable: bool


def compare_savings(native_tokens: int | None, converted_tokens: int) -> SavingsResult:
    """Compare native-upload token cost against converted-Markdown token
    cost. `native_tokens=None` means there's no meaningful native-cost
    baseline for this format (e.g. a .docx, which Claude already reads as
    text) — in that case we don't claim any multiplier."""
    if native_tokens is None or converted_tokens <= 0:
        return SavingsResult(native_tokens or 0, converted_tokens, 0.0, 0.0, "n/a", applicable=False)

    multiplier = native_tokens / converted_tokens if converted_tokens else 0.0
    pct_saved = max(0.0, (1 - converted_tokens / native_tokens) * 100) if native_tokens else 0.0

    if multiplier >= 2:
        verdict = "Strong savings"
    elif multiplier >= 1.15:
        verdict = "Moderate savings"
    elif multiplier >= 0.9:
        verdict = "No real difference"
    else:
        verdict = "Conversion adds overhead"

    return SavingsResult(native_tokens, converted_tokens, round(multiplier, 1), round(pct_saved, 1), verdict, applicable=True)

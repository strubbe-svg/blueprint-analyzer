"""
extract.py
PDF → (high-res JPEG images, vector text JSON) per page.

Uses:
  pdfplumber  — vector text extraction with bounding boxes
  pdf2image   — high-quality page rendering via poppler
  Pillow      — image resizing / compression
"""

from __future__ import annotations

import base64
import json
from io import BytesIO
from pathlib import Path

import pdfplumber
from pdf2image import convert_from_path
from PIL import Image

# Cap longest image dimension before encoding to stay under API limits
MAX_DIMENSION_PX = 4000
RENDER_DPI = 200          # 200 DPI balances quality vs file size for most blueprints
JPEG_QUALITY = 92         # High quality — blueprints have fine linework


# ── Vector text ───────────────────────────────────────────────────────────────

def _extract_vector_text(pdf_path: str) -> list[dict]:
    """
    Extract every word from the PDF vector layer with its bounding box.
    Returns a list of page dicts, one per page.
    """
    pages = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            words = page.extract_words(
                x_tolerance=3,
                y_tolerance=3,
                keep_blank_chars=False,
                use_text_flow=False,
                extra_attrs=["fontname", "size"],
            )

            pages.append({
                "page":            page_num,
                "page_width_pts":  round(float(page.width), 2),
                "page_height_pts": round(float(page.height), 2),
                "word_count":      len(words),
                "words": [
                    {
                        "text": w["text"],
                        "x0":   round(w["x0"],    2),
                        "y0":   round(w["top"],    2),
                        "x1":   round(w["x1"],    2),
                        "y1":   round(w["bottom"], 2),
                        "font": w.get("fontname", ""),
                        "size": round(float(w["size"]), 1) if w.get("size") else 0,
                    }
                    for w in words
                ],
            })

    return pages


# ── Image rendering ───────────────────────────────────────────────────────────

def _render_pages(pdf_path: str, dpi: int = RENDER_DPI) -> list[dict]:
    """
    Render each page as a JPEG.
    Returns list of {page, width_px, height_px, image_b64, size_kb}.
    """
    raw_images = convert_from_path(pdf_path, dpi=dpi, fmt="png", thread_count=2)

    results = []
    for page_num, img in enumerate(raw_images, 1):
        w, h = img.size

        # Downscale if the longest dimension exceeds the cap
        max_dim = max(w, h)
        if max_dim > MAX_DIMENSION_PX:
            scale = MAX_DIMENSION_PX / max_dim
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
            w, h = img.size

        buf = BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=JPEG_QUALITY)
        buf.seek(0)
        img_b64 = base64.b64encode(buf.read()).decode("utf-8")

        results.append({
            "page":       page_num,
            "width_px":   w,
            "height_px":  h,
            "image_b64":  img_b64,
            "size_kb":    len(buf.getvalue()) // 1024,
        })

    return results


# ── Public entry point ────────────────────────────────────────────────────────

def extract(pdf_path: str, output_dir: str) -> dict:
    """
    Full extraction pass:
      1. Renders every page as a high-res JPEG
      2. Extracts all vector text with positional data
      3. Saves vector_text.json to output_dir
    Returns a dict consumed by the analysis stage.
    """
    pdf_path   = Path(pdf_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"  [extract] Vector text …")
    pages_text = _extract_vector_text(str(pdf_path))
    text_path  = output_dir / "vector_text.json"
    text_path.write_text(json.dumps(pages_text, indent=2))
    total_words = sum(p["word_count"] for p in pages_text)
    print(f"    → {len(pages_text)} page(s), {total_words} words → {text_path.name}")

    print(f"  [extract] Rendering pages at {RENDER_DPI} DPI …")
    pages_images = _render_pages(str(pdf_path), dpi=RENDER_DPI)
    for p in pages_images:
        print(f"    → Page {p['page']}: {p['width_px']}×{p['height_px']} px  ({p['size_kb']} KB)")

    return {
        "pdf_name":     pdf_path.stem,
        "total_pages":  len(pages_images),
        "pages_images": pages_images,
        "pages_text":   pages_text,
    }

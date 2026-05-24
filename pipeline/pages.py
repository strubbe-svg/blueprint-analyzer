"""
pages.py
Page selection utility — extracts a subset of pages from a PDF and
saves them as a new single PDF before the analysis pipeline runs.

Supported --pages syntax (mirrors qpdf convention):
  "5"        → page 5 only
  "3-7"      → pages 3 through 7 (inclusive)
  "1,4,9"    → pages 1, 4, and 9
  "1,3-5,8"  → pages 1, 3, 4, 5, and 8

All page numbers are 1-based (as printed on the document).
"""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader, PdfWriter


# ── Page-spec parser ──────────────────────────────────────────────────────────

def parse_page_spec(spec: str, total_pages: int) -> list[int]:
    """
    Convert a page spec string into a sorted, deduplicated list of
    1-based page numbers, validated against total_pages.

    Examples:
      parse_page_spec("3",     10) → [3]
      parse_page_spec("3-6",   10) → [3, 4, 5, 6]
      parse_page_spec("1,4,9", 10) → [1, 4, 9]
      parse_page_spec("1,3-5", 10) → [1, 3, 4, 5]
    """
    pages: set[int] = set()

    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue

        if "-" in part:
            bounds = part.split("-")
            if len(bounds) != 2:
                raise ValueError(f"Invalid range '{part}' — use format 'start-end' e.g. '3-7'")
            start, end = int(bounds[0]), int(bounds[1])
            if start > end:
                raise ValueError(f"Range start ({start}) must be ≤ end ({end})")
            pages.update(range(start, end + 1))
        else:
            pages.add(int(part))

    # Validate
    invalid = [p for p in pages if p < 1 or p > total_pages]
    if invalid:
        raise ValueError(
            f"Page(s) {sorted(invalid)} are out of range. "
            f"This PDF has {total_pages} page(s)."
        )

    return sorted(pages)


# ── Extraction ────────────────────────────────────────────────────────────────

def extract_pages(pdf_path: str, page_spec: str, output_dir: str) -> str:
    """
    Extract the pages described by page_spec from pdf_path and write
    them to a new PDF in output_dir.

    Returns the path to the extracted PDF.
    """
    pdf_path   = Path(pdf_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    reader      = PdfReader(str(pdf_path))
    total_pages = len(reader.pages)

    page_numbers = parse_page_spec(page_spec, total_pages)
    print(f"  [pages] Extracting page(s) {page_numbers} from {pdf_path.name} "
          f"({total_pages} total pages)")

    writer = PdfWriter()
    for pnum in page_numbers:
        writer.add_page(reader.pages[pnum - 1])   # pypdf is 0-indexed

    # Name: original_stem + page spec (sanitised) + .pdf
    safe_spec = page_spec.replace(",", "_").replace("-", "to")
    out_name  = f"{pdf_path.stem}_pages{safe_spec}.pdf"
    out_path  = output_dir / out_name

    with open(out_path, "wb") as f:
        writer.write(f)

    print(f"  [pages] Saved {len(page_numbers)} page(s) → {out_path}")
    return str(out_path)

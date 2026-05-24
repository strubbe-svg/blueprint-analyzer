"""
main.py
CLI entry point for the blueprint analysis pipeline.

Usage:
  # Analyze all pages
  python pipeline/main.py data/input/blueprint.pdf

  # Analyze specific pages only (extracted to a new PDF first)
  python pipeline/main.py data/input/blueprint.pdf --pages 3
  python pipeline/main.py data/input/blueprint.pdf --pages 3-6
  python pipeline/main.py data/input/blueprint.pdf --pages 1,4,9
  python pipeline/main.py data/input/blueprint.pdf --pages 1,3-5,8

Environment:
  ANTHROPIC_API_KEY  — required
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import anthropic

# Allow running from repo root or from pipeline/ directory
sys.path.insert(0, str(Path(__file__).parent))

from extract import extract
from analyze import analyze_page
from verify  import verify_page
from merge   import merge
from pages   import extract_pages


def run(pdf_path: str, output_base: str = "data/output", page_spec: str | None = None) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY environment variable is not set.")

    client   = anthropic.Anthropic(api_key=api_key)
    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    # ── Optional page extraction ───────────────────────────────────────────
    # If --pages was given, slice the PDF first and run the pipeline on
    # the extracted subset. The output folder reflects the page selection
    # so re-running different page ranges never overwrites each other.
    if page_spec:
        safe_spec  = page_spec.replace(",", "_").replace("-", "to")
        output_dir = Path(output_base) / f"{pdf_path.stem}_pages{safe_spec}"
        output_dir.mkdir(parents=True, exist_ok=True)

        _banner(f"Blueprint Analyzer  ·  {pdf_path.name}  ·  pages {page_spec}")
        print(f"\nSTEP 0 — Page extraction: slicing pages {page_spec}")
        pdf_path = Path(extract_pages(str(pdf_path), page_spec, str(output_dir)))
    else:
        output_dir = Path(output_base) / pdf_path.stem
        output_dir.mkdir(parents=True, exist_ok=True)
        _banner(f"Blueprint Analyzer  ·  {pdf_path.name}")

    # ── Step 1: Extract ────────────────────────────────────────────────────
    print("\nSTEP 1 — Extract: rendering pages + vector text")
    extracted   = extract(str(pdf_path), str(output_dir))
    total_pages = extracted["total_pages"]

    # ── Steps 2 & 3: Analyze + Verify each page ───────────────────────────
    page_results: list[dict] = []

    for i in range(total_pages):
        page_img = extracted["pages_images"][i]
        page_txt = extracted["pages_text"][i] if i < len(extracted["pages_text"]) else {}
        page_num = page_img["page"]

        print(f"\nSTEP 2 — Pass 1 extraction  [page {page_num}/{total_pages}]")
        pass1 = analyze_page(
            page_image=page_img,
            page_text=page_txt,
            blueprint_id=pdf_path.stem,
            total_pages=total_pages,
            client=client,
        )
        _save(pass1, output_dir / f"page_{page_num:02d}_pass1.json")
        print(f"  → {len(pass1.get('spaces', []))} spaces  |  {_tokens(pass1)} tokens")

        print(f"\nSTEP 3 — Pass 2 verification [page {page_num}/{total_pages}]")
        pass2 = verify_page(
            page_image=page_img,
            pass1_result=pass1,
            client=client,
        )
        _save(pass2, output_dir / f"page_{page_num:02d}_pass2.json")
        print(f"  → {len(pass2.get('corrections_made', []))} correction(s)  |  {_tokens(pass2)} tokens")

        page_results.append(pass2)

    # ── Step 4: Merge ──────────────────────────────────────────────────────
    print("\nSTEP 4 — Merge: assembling final report")
    report  = merge(pdf_path.stem, page_results, str(output_dir))
    summary = report["summary"]
    tokens  = report["token_usage"]

    _banner("COMPLETE")
    print(f"  Spaces found     : {summary['total_spaces']}")
    print(f"  Total area       : {summary.get('total_area_sqft') or 'N/A'} sq ft")
    print(f"  Data quality     : {summary['data_quality_score']}")
    print(f"  Uncertain fields : {summary['total_uncertain_fields']}")
    print(f"  Corrections made : {summary['total_corrections_made']}")
    print(f"  API cost (est.)  : ~${tokens['estimated_cost_usd']:.4f}")
    print(f"  Output           : {output_dir}/")

    return report


# ── Utilities ─────────────────────────────────────────────────────────────────

def _save(data: dict, path: Path) -> None:
    path.write_text(json.dumps(data, indent=2))


def _tokens(result: dict) -> str:
    meta = result.get("_meta", {})
    return f"{meta.get('input_tokens', 0) + meta.get('output_tokens', 0):,}"


def _banner(msg: str) -> None:
    bar = "═" * (len(msg) + 4)
    print(f"\n╔{bar}╗")
    print(f"║  {msg}  ║")
    print(f"╚{bar}╝")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Blueprint Analyzer — two-pass AI extraction pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
page spec examples:
  --pages 3          single page
  --pages 3-6        range (inclusive)
  --pages 1,4,9      non-contiguous pages
  --pages 1,3-5,8    mixed ranges and singles
        """,
    )
    parser.add_argument("pdf_path",     help="Path to the blueprint PDF file")
    parser.add_argument("--output-dir", default="data/output",
                        help="Base output directory (default: data/output)")
    parser.add_argument("--pages",      default=None,
                        help="Pages to analyze, e.g. '3' or '3-6' or '1,4,9'")
    args = parser.parse_args()

    try:
        run(args.pdf_path, args.output_dir, args.pages)
    except (FileNotFoundError, EnvironmentError, ValueError) as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)

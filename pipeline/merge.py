"""
merge.py
Assembles per-page Pass 2 results into a single structured report
and generates a human-readable Markdown summary.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


# ── Stats helpers ─────────────────────────────────────────────────────────────

def _quality_score(spaces: list[dict]) -> str:
    if not spaces:
        return "N/A — no spaces found"
    high = sum(
        1 for s in spaces
        if s.get("dimensions", {}).get("width_confidence")  == "high"
        and s.get("dimensions", {}).get("length_confidence") == "high"
    )
    pct = (high / len(spaces)) * 100
    label = "🟢 High" if pct >= 80 else "🟡 Medium" if pct >= 50 else "🔴 Low"
    return f"{label} ({pct:.0f}% of spaces have high-confidence dimensions)"


def _compute_summary(pages: list[dict]) -> dict:
    all_spaces:      list[dict] = []
    total_uncertain: int = 0
    total_corrections: int = 0

    for page in pages:
        spaces = page.get("spaces", [])
        all_spaces.extend(spaces)
        for space in spaces:
            total_uncertain += len(space.get("uncertain_fields", []))
        total_corrections += len(page.get("corrections_made", []))

    total_area  = sum(
        s["dimensions"]["area_sqft"]
        for s in all_spaces
        if s.get("dimensions", {}).get("area_sqft")
    )
    area_count  = sum(
        1 for s in all_spaces
        if s.get("dimensions", {}).get("area_sqft")
    )

    type_counts: dict[str, int] = {}
    for s in all_spaces:
        t = s.get("type", "other")
        type_counts[t] = type_counts.get(t, 0) + 1

    return {
        "total_spaces":          len(all_spaces),
        "total_area_sqft":       round(total_area, 1) if area_count else None,
        "area_coverage":         f"{area_count}/{len(all_spaces)} spaces have area data",
        "room_type_breakdown":   type_counts,
        "total_uncertain_fields":  total_uncertain,
        "total_corrections_made":  total_corrections,
        "data_quality_score":    _quality_score(all_spaces),
    }


def _token_cost(pages: list[dict]) -> dict:
    total_in = total_out = 0
    for page in pages:
        meta = page.get("_meta", {})
        total_in  += meta.get("input_tokens",  0)
        total_out += meta.get("output_tokens", 0)
    # Approximate cost at Sonnet 4 rates ($3/$15 per 1M tokens)
    cost = (total_in * 3 + total_out * 15) / 1_000_000
    return {
        "input_tokens":  total_in,
        "output_tokens": total_out,
        "estimated_cost_usd": round(cost, 4),
    }


# ── Markdown generation ───────────────────────────────────────────────────────

def _to_markdown(report: dict) -> str:
    lines: list[str] = []
    pdf_name = report.get("pdf_name", "Unknown")
    ts       = report.get("generated_at", "")[:10]
    summary  = report.get("summary", {})
    tokens   = report.get("token_usage", {})

    lines += [
        f"# Blueprint Analysis: {pdf_name}",
        f"*Generated: {ts}*",
        "",
        "## Summary",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total spaces found      | {summary.get('total_spaces', 0)} |",
        f"| Total area              | {summary.get('total_area_sqft') or 'N/A'} sq ft |",
        f"| Pages analyzed          | {report.get('total_pages', 0)} |",
        f"| Data quality            | {summary.get('data_quality_score', 'N/A')} |",
        f"| Uncertain fields        | {summary.get('total_uncertain_fields', 0)} — review recommended |",
        f"| Pass 2 corrections made | {summary.get('total_corrections_made', 0)} |",
        f"| API tokens used         | {tokens.get('input_tokens', 0):,} in / {tokens.get('output_tokens', 0):,} out |",
        f"| Estimated API cost      | ~${tokens.get('estimated_cost_usd', 0):.4f} |",
        "",
    ]

    breakdown = summary.get("room_type_breakdown", {})
    if breakdown:
        lines.append("## Room Type Breakdown")
        for rtype, count in sorted(breakdown.items(), key=lambda x: -x[1]):
            lines.append(f"- **{rtype.title()}**: {count}")
        lines.append("")

    for page in report.get("pages", []):
        page_num    = page.get("page", "?")
        spaces      = page.get("spaces", [])
        corrections = page.get("corrections_made", [])
        warnings    = page.get("extraction_warnings", [])

        lines += [
            f"## Page {page_num}",
            f"**Scale:** {page.get('scale') or 'Not detected'}  ",
            f"**Spaces found:** {len(spaces)}",
            "",
        ]

        if spaces:
            lines += [
                "| Room | W (ft) | L (ft) | Area (sqft) | Conf (W/L) | Uncertain |",
                "|------|--------|--------|-------------|-----------|-----------|",
            ]
            for s in spaces:
                dims      = s.get("dimensions", {})
                w         = dims.get("width_ft")
                l         = dims.get("length_ft")
                a         = dims.get("area_sqft")
                w_c       = dims.get("width_confidence", "?")
                l_c       = dims.get("length_confidence", "?")
                uncertain = ", ".join(s.get("uncertain_fields", [])) or "—"
                verified  = "✅" if s.get("verified") else "❓"
                lines.append(
                    f"| {verified} {s.get('name', '?')} "
                    f"| {w or '—'} | {l or '—'} | {a or '—'} "
                    f"| {w_c}/{l_c} | {uncertain} |"
                )
            lines.append("")

        if corrections:
            lines.append("**Pass 2 Corrections:**")
            for c in corrections:
                lines.append(f"- {c}")
            lines.append("")

        if warnings:
            lines.append("**⚠️ Warnings:**")
            for w in warnings:
                lines.append(f"- {w}")
            lines.append("")

    return "\n".join(lines)


# ── Public entry point ────────────────────────────────────────────────────────

def merge(pdf_name: str, pages: list[dict], output_dir: str) -> dict:
    """
    Merge all per-page results → report.json + report.md in output_dir.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "pdf_name":     pdf_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_pages":  len(pages),
        "summary":      _compute_summary(pages),
        "token_usage":  _token_cost(pages),
        "pages":        pages,
    }

    (output_dir / "report.json").write_text(json.dumps(report, indent=2))
    (output_dir / "report.md").write_text(_to_markdown(report))

    return report

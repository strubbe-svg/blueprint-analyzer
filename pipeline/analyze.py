"""
analyze.py
Pass 1: Claude extracts structured room/space data from blueprint image + vector text.

Confidence tiers:
  high   — value is an explicit callout/label in the drawing
  medium — inferred by measuring against the scale bar
  low    — estimated from spatial reasoning only
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import anthropic

MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 4096

# ── Output schema (sent verbatim in the prompt) ───────────────────────────────

SCHEMA: dict[str, Any] = {
    "blueprint_id": "string — PDF filename stem",
    "page": "integer",
    "total_pages": "integer",
    "scale": "string — e.g. '1/4\" = 1\\'-0\\\"', or null if not found",
    "scale_confidence": "high | medium | low | null",
    "spaces": [
        {
            "id": "string — sequential, e.g. 'space_001'",
            "name": "string — exact label as visible in drawing",
            "type": "bedroom | bathroom | kitchen | living | dining | hallway | garage | utility | closet | office | laundry | other",
            "dimensions": {
                "width_ft":          "number or null",
                "width_confidence":  "high | medium | low | null",
                "length_ft":         "number or null",
                "length_confidence": "high | medium | low | null",
                "area_sqft":         "number or null",
                "area_confidence":   "high | medium | low | null",
                "ceiling_height_ft": "number or null",
                "ceiling_confidence":"high | medium | low | null",
            },
            "features": {
                "door_count":      "integer",
                "window_count":    "integer",
                "closet_count":    "integer",
                "special_elements": ["array of strings — e.g. 'walk-in closet', 'island', 'built-in shelving'"],
            },
            "adjacent_spaces":   ["array of room name strings"],
            "uncertain_fields":  ["array of field names that are uncertain — e.g. 'width_ft', 'door_count'"],
            "notes":             "string — any relevant observations about this space",
        }
    ],
    "structural": {
        "exterior_wall_thickness_in": "number or null",
        "interior_wall_thickness_in": "number or null",
        "wall_confidence":            "high | medium | low",
    },
    "unmatched_annotations": ["array of text labels found in the drawing that could not be mapped to a space"],
    "extraction_warnings":   ["array of strings describing issues encountered"],
}

SYSTEM_PROMPT = """You are a precision architectural blueprint analyzer with deep expertise in reading construction drawings.

Your task is to extract structured data from a blueprint image with maximum accuracy.

STRICT RULES:
1. Only report what you can CLEARLY see. Never infer, estimate, or fabricate values.
2. Vector text extracted directly from the PDF is authoritative — use those exact values for dimensions and labels.
3. Confidence levels:
     "high"   = value is an explicit callout or label in the drawing
     "medium" = inferred by measuring against the visible scale bar
     "low"    = estimated from spatial reasoning only
4. Populate "uncertain_fields" with the name of EVERY field you are not fully confident about.
5. If you cannot read a label or dimension clearly, set the value to null and add the field name to "uncertain_fields".
6. Do not skip small spaces — include closets, hallways, bathrooms, utility rooms, etc.
7. Return ONLY valid JSON matching the schema exactly. No preamble, no explanation, no markdown fences."""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_vector_text(page_text: dict) -> str:
    """Reconstruct vector text as readable lines for the prompt."""
    words = page_text.get("words", [])
    if not words:
        return "No vector text found on this page — rely on image only."

    # Group words into lines by proximity on the Y axis
    sorted_words = sorted(words, key=lambda w: (round(w["y0"] / 12) * 12, w["x0"]))

    lines: list[str] = []
    current_y: float | None = None
    current_line: list[str] = []

    for word in sorted_words:
        y_bucket = round(word["y0"] / 12) * 12
        if current_y is None or abs(y_bucket - current_y) > 12:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word["text"]]
            current_y = y_bucket
        else:
            current_line.append(word["text"])

    if current_line:
        lines.append(" ".join(current_line))

    # Deduplicate and remove single-character noise
    seen: set[str] = set()
    clean: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and stripped not in seen and len(stripped) > 1:
            seen.add(stripped)
            clean.append(stripped)

    return "\n".join(clean[:250])   # cap to avoid prompt bloat


def _strip_fences(text: str) -> str:
    """Remove markdown code fences if Claude adds them despite instructions."""
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        # parts[1] is the content (possibly starting with 'json\n')
        content = parts[1] if len(parts) > 1 else text
        if content.startswith("json"):
            content = content[4:]
        return content.strip()
    return text


# ── Public entry point ────────────────────────────────────────────────────────

def analyze_page(
    page_image: dict,
    page_text:  dict,
    blueprint_id: str,
    total_pages:  int,
    client: anthropic.Anthropic,
) -> dict:
    """
    Pass 1: send image + vector text to Claude and return structured extraction.
    """
    page_num    = page_image["page"]
    vector_text = _format_vector_text(page_text)

    user_prompt = f"""Analyze this architectural blueprint — page {page_num} of {total_pages}.

VECTOR TEXT EXTRACTED DIRECTLY FROM PDF (authoritative — use for exact values):
---
{vector_text}
---

Extract ALL rooms, spaces, and structural information visible on this page.

Return a JSON object matching EXACTLY this schema:
{json.dumps(SCHEMA, indent=2)}

Field values for this extraction:
  blueprint_id  = "{blueprint_id}"
  page          = {page_num}
  total_pages   = {total_pages}

REMINDER: Return ONLY the JSON object. No other text."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type":       "base64",
                            "media_type": "image/jpeg",
                            "data":       page_image["image_b64"],
                        },
                    },
                    {"type": "text", "text": user_prompt},
                ],
            }
        ],
    )

    raw = _strip_fences(response.content[0].text)

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        result = {
            "error":        f"JSON parse failed: {exc}",
            "raw_response": raw[:800],
            "page":         page_num,
            "spaces":       [],
        }

    result["_meta"] = {
        "pass":          1,
        "model":         MODEL,
        "timestamp":     datetime.now(timezone.utc).isoformat(),
        "input_tokens":  response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }

    return result

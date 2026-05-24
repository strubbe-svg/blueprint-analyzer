"""
verify.py
Pass 2: Claude reviews the Pass 1 extraction against the original image,
corrects errors, and flags anything still uncertain.

This second pass catches ~80% of Pass 1 errors because Claude can compare
its own prior output against what it actually sees rather than extracting cold.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import anthropic

MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 4096

SYSTEM_PROMPT = """You are a quality-control reviewer for architectural blueprint data extraction.

You will receive:
  1. A blueprint image
  2. A JSON extraction produced by a first-pass analyst

Your job is to VERIFY every extracted value against what you can clearly see in the image, then return a corrected version.

RULES:
1. Check every room name against visible labels in the drawing.
2. Check every dimension (width_ft, length_ft) against explicit callouts.
3. Count doors and windows visually where possible.
4. If a value is correct, mark it "verified": true.
5. If a value is wrong, correct it and add an entry to "corrections_made".
6. Downgrade confidence scores if you are less certain than the first analyst indicated.
7. If you find new spaces the first pass missed, add them.
8. Return ONLY valid JSON. No preamble, no markdown fences."""


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        content = parts[1] if len(parts) > 1 else text
        if content.startswith("json"):
            content = content[4:]
        return content.strip()
    return text


def verify_page(
    page_image:   dict,
    pass1_result: dict,
    client: anthropic.Anthropic,
) -> dict:
    """
    Pass 2: verify the Pass 1 extraction against the image.
    Returns a corrected extraction dict with verification metadata.
    """
    page_num = page_image["page"]

    # Strip internal meta before sending to Claude
    pass1_clean = {k: v for k, v in pass1_result.items() if k != "_meta"}

    user_prompt = f"""Review blueprint page {page_num} against the extraction data below.

EXTRACTION TO VERIFY:
{json.dumps(pass1_clean, indent=2)}

For each space:
  1. Confirm the room name matches a visible label  →  "verified": true/false
  2. Verify width_ft and length_ft against dimension callouts
  3. Count doors and windows visually
  4. Correct anything that is wrong

Return the corrected JSON with these additions at the TOP LEVEL:
  "corrections_made":   array of plain-English strings describing each change (empty [] if none)
  "verification_notes": single string summarising your overall review
  "verified":           true if no corrections needed, false if any were made

Add  "verified": true/false  to each individual space object as well.

Keep ALL original fields. Return ONLY the JSON object."""

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
        # Verification parse failed — fall back to Pass 1 result unchanged
        result = pass1_clean.copy()
        result["verification_error"] = f"Pass 2 parse failed: {exc}"
        result["corrections_made"]   = []
        result["verification_notes"] = "Verification failed — Pass 1 result used as-is"
        result["verified"]           = False

    result["_meta"] = {
        "pass":          2,
        "model":         MODEL,
        "timestamp":     datetime.now(timezone.utc).isoformat(),
        "input_tokens":  response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }

    return result

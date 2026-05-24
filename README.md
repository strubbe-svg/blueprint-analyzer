# blueprint-analyzer

Two-pass AI pipeline for extracting structured room data from architectural blueprint PDFs with high accuracy.

## How it works

| Pass | What happens |
|------|-------------|
| **Extract** | Renders each page at 200 DPI and pulls all vector text (exact dimensions/labels) with `pdfplumber` |
| **Pass 1** | Claude receives the image + vector text and extracts rooms, dimensions, features into structured JSON with confidence scores |
| **Pass 2** | Claude verifies its own Pass 1 output against the image, corrects errors, and flags anything still uncertain |
| **Merge** | All pages are combined into a single `report.json` + `report.md` |

### Why two passes?

Pass 1 extracts cold. Pass 2 compares — Claude can catch its own errors at a significantly higher rate when given its prior output alongside the original image. Vector text extraction removes the biggest failure mode (misreading small dimension callouts).

## Output

For each PDF, the pipeline writes to `data/output/<pdf_name>/`:

```
vector_text.json          ← All text extracted from PDF vector layer
page_01_pass1.json        ← Raw Pass 1 extraction
page_01_pass2.json        ← Verified + corrected extraction
report.json               ← Full merged report (all pages)
report.md                 ← Human-readable summary table
```

### report.json structure

```json
{
  "pdf_name": "floor_plan",
  "generated_at": "ISO8601",
  "total_pages": 2,
  "summary": {
    "total_spaces": 14,
    "total_area_sqft": 2340,
    "data_quality_score": "🟢 High (85% of spaces have high-confidence dimensions)",
    "total_uncertain_fields": 3,
    "total_corrections_made": 2
  },
  "pages": [
    {
      "page": 1,
      "scale": "1/4\" = 1'-0\"",
      "spaces": [
        {
          "id": "space_001",
          "name": "Master Bedroom",
          "type": "bedroom",
          "dimensions": {
            "width_ft": 14.5,
            "width_confidence": "high",
            "length_ft": 16.0,
            "length_confidence": "high",
            "area_sqft": 232
          },
          "features": { "door_count": 2, "window_count": 3, "closet_count": 1 },
          "verified": true,
          "uncertain_fields": []
        }
      ],
      "corrections_made": [],
      "verification_notes": "All dimensions verified against callouts."
    }
  ]
}
```

## Running locally

```bash
# Install dependencies
pip install -r requirements.txt

# macOS/Linux also needs poppler:
brew install poppler           # macOS
sudo apt install poppler-utils # Ubuntu

# Run
export ANTHROPIC_API_KEY=sk-ant-...
python pipeline/main.py data/input/floor_plan.pdf
```

## GitHub Actions (automatic)

The workflow triggers automatically when a PDF is pushed to `data/input/`:

```bash
git add data/input/floor_plan.pdf
git commit -m "add floor plan"
git push
# → Action runs, results committed to data/output/floor_plan/
```

Or trigger manually: **Actions → Analyze Blueprint → Run workflow**.

### Required secret

Add `ANTHROPIC_API_KEY` under **Settings → Secrets and variables → Actions**.

### PDF size note

GitHub has a 100 MB file size limit. For large blueprint sets, use [Git LFS](https://git-lfs.com):
```bash
git lfs install
git lfs track "*.pdf"
git add .gitattributes
```

## Estimated API cost

Each page requires two Claude Sonnet API calls (Pass 1 + Pass 2).
Typical cost: **$0.05–$0.15 per page** depending on complexity.
Reported in `report.md` after each run.

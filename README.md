# blueprint-analyzer

Two-pass AI pipeline for extracting structured room data from architectural blueprint PDFs with high accuracy.

## How it works

| Step | What happens |
|------|-------------|
| **0 — Page extraction** *(optional)* | Slices specific pages from a larger PDF using `pypdf` before any analysis runs |
| **1 — Extract** | Renders each page at 200 DPI and pulls all vector text (exact dimensions/labels) with `pdfplumber` |
| **2 — Pass 1** | Claude receives the image + vector text and extracts rooms, dimensions, and features into structured JSON with confidence scores |
| **3 — Pass 2** | Claude verifies its own Pass 1 output against the image, corrects errors, and flags remaining uncertainty |
| **4 — Merge** | All pages combined into a single `report.json` + `report.md` |

---

## Step-by-step: analyzing a single page from a larger document

This is the most common scenario — a full architectural drawing set (cover sheet, site plan, floor plan, elevations, details) where you only want the floor plan page(s).

### Step 1 — Find your page number

Open your blueprint PDF in any viewer (Preview, Adobe Acrobat, browser). Note the **page number** of the floor plan you want. Page numbers are 1-based (the first page of the file is page 1, regardless of what the sheet number says on the drawing itself).

> **Tip:** A typical set might look like:
> - Page 1 — Cover sheet / index
> - Page 2 — Site plan
> - **Page 3 — First floor plan** ← this is what you want
> - Page 4 — Second floor plan
> - Pages 5–12 — Elevations, sections, details

### Step 2 — Add the PDF to the repo

```bash
# From your local clone of the repo
cp /path/to/your/blueprints.pdf data/input/blueprints.pdf
git add data/input/blueprints.pdf
git commit -m "add blueprint set"
git push
```

> **Large files (>50 MB):** Use Git LFS first:
> ```bash
> git lfs install
> git lfs track "*.pdf"
> git add .gitattributes && git commit -m "track PDFs with LFS"
> ```

### Step 3 — Trigger the workflow with your page number

Go to: **GitHub → strubbe-svg/blueprint-analyzer → Actions → Analyze Blueprint → Run workflow**

Fill in the two fields:

| Field | Example | Notes |
|-------|---------|-------|
| `pdf_filename` | `blueprints.pdf` | Must match the filename in `data/input/` |
| `pages` | `3` | The page number you identified in Step 1 |

Click **Run workflow**.

#### Page spec examples

| You want | Enter in `pages` field |
|----------|----------------------|
| Page 3 only | `3` |
| Pages 3 through 6 | `3-6` |
| Pages 3 and 7 (non-contiguous) | `3,7` |
| Pages 1, 3 through 5, and 8 | `1,3-5,8` |
| All pages in the PDF | *(leave blank)* |

### Step 4 — Check the results

The action runs in ~2–3 minutes per page. When complete:

1. **Job Summary tab** — the markdown report renders inline in the Actions UI
2. **Artifacts** — download the full output folder (JSON + MD files)
3. **Repo** — results are auto-committed to `data/output/`

Output folder naming:
- All pages → `data/output/blueprints/`
- Page 3 only → `data/output/blueprints_pages3/`
- Pages 3-6 → `data/output/blueprints_pages3to6/`

### Step 5 — Review uncertain fields

Open `report.md` and look at the **Uncertain** column in each room's row. Any field listed there was not clearly readable — those are the ones worth a manual spot-check against your physical PDF.

---

## Output structure

For each run, the pipeline writes to `data/output/<name>/`:

```
blueprints_pages3/
├── blueprints_pages3.pdf       ← The extracted page(s) as a standalone PDF
├── vector_text.json            ← All text from the PDF vector layer
├── page_01_pass1.json          ← Raw Pass 1 extraction
├── page_01_pass2.json          ← Verified + corrected extraction
├── report.json                 ← Full merged report
└── report.md                   ← Human-readable summary table
```

### report.json structure (key fields)

```json
{
  "pdf_name": "blueprints_pages3",
  "summary": {
    "total_spaces": 14,
    "total_area_sqft": 2340,
    "data_quality_score": "🟢 High (85% of spaces have high-confidence dimensions)",
    "total_uncertain_fields": 3,
    "total_corrections_made": 2
  },
  "pages": [{
    "scale": "1/4\" = 1'-0\"",
    "spaces": [{
      "id": "space_001",
      "name": "Master Bedroom",
      "type": "bedroom",
      "dimensions": {
        "width_ft": 14.5,  "width_confidence": "high",
        "length_ft": 16.0, "length_confidence": "high",
        "area_sqft": 232
      },
      "features": { "door_count": 2, "window_count": 3 },
      "verified": true,
      "uncertain_fields": []
    }],
    "corrections_made": [],
    "verification_notes": "All dimensions verified against callouts."
  }]
}
```

---

## Running locally

```bash
# Install Python dependencies
pip install -r requirements.txt

# Install poppler (required by pdf2image)
brew install poppler            # macOS
sudo apt install poppler-utils  # Ubuntu/Debian

# Set your API key
export ANTHROPIC_API_KEY=sk-ant-...

# Analyze all pages
python pipeline/main.py data/input/blueprints.pdf

# Analyze page 3 only
python pipeline/main.py data/input/blueprints.pdf --pages 3

# Analyze pages 3 through 6
python pipeline/main.py data/input/blueprints.pdf --pages 3-6

# Analyze pages 1, 4, and 9
python pipeline/main.py data/input/blueprints.pdf --pages 1,4,9
```

---

## Setup checklist

- [ ] Add `ANTHROPIC_API_KEY` secret: **Settings → Secrets and variables → Actions → New repository secret**
- [ ] For PDFs > 50 MB: enable Git LFS (`git lfs install && git lfs track "*.pdf"`)

## Estimated API cost

Each page = two Claude Sonnet API calls (Pass 1 + Pass 2).
Typical cost: **$0.05–$0.15 per page**. Reported in every `report.md`.

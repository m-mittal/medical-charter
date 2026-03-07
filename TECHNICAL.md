# Technical Documentation

## Table of Contents

- [System Overview](#system-overview)
- [Architecture](#architecture)
- [Processing Pipeline](#processing-pipeline)
  - [Stage 1 — Raw Extraction](#stage-1--raw-extraction)
  - [Stage 2 — Processing & Normalization](#stage-2--processing--normalization)
  - [Stage 3 — Categorization](#stage-3--categorization)
- [PDF Text Extraction](#pdf-text-extraction)
- [Line-Level Parsing](#line-level-parsing)
- [Unit Handling Pipeline](#unit-handling-pipeline)
- [Configuration Reference](#configuration-reference)
- [API Reference](#api-reference)
- [Frontend Architecture](#frontend-architecture)
- [Cache Files](#cache-files)
- [Adding Support for a New Lab](#adding-support-for-a-new-lab)
- [Troubleshooting](#troubleshooting)

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     PDF Blood Reports                           │
│              (./data/yyyy-mm-dd_Name.pdf)                       │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                   PROCESSING PIPELINE                           │
│                                                                 │
│  ┌─────────────┐   ┌──────────────┐   ┌───────────────────┐    │
│  │  Stage 1    │──▶│   Stage 2    │──▶│     Stage 3       │    │
│  │  Extract    │   │   Process    │   │    Categorize     │    │
│  │ (raw data)  │   │ (normalize)  │   │  (group for UI)   │    │
│  └─────────────┘   └──────────────┘   └───────────────────┘    │
│        │                  │                     │               │
│        ▼                  ▼                     ▼               │
│  stage1_raw.csv   stage2_processed.csv  stage3_categorized.csv  │
└─────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Flask API Server                           │
│          /api/data  /api/trend  /api/summary  /api/refresh      │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Web Dashboard                               │
│    Consolidated Table │ Trend Charts │ Pivot View               │
└─────────────────────────────────────────────────────────────────┘
```

---

## Architecture

### File Structure

```
medicalReportCharter/
├── data/                          # Source PDF reports
│   └── yyyy-mm-dd_ReportName.pdf
├── cache/                         # Pipeline output (auto-generated)
│   ├── stage1_raw.csv             # Raw extracted values
│   ├── stage2_processed.csv       # Normalized & converted
│   └── stage3_categorized.csv     # Final, UI-ready data
├── config.yaml                    # All user-configurable data
├── pdf_processor.py               # Three-stage pipeline engine
├── app.py                         # Flask web server
├── templates/
│   └── index.html                 # Dashboard layout
├── static/
│   ├── css/style.css              # Styling
│   └── js/app.js                  # Frontend logic
└── requirements.txt               # Python dependencies
```

### Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| PDF text extraction | pdfplumber | Native text-based PDFs |
| OCR fallback | pytesseract + pdf2image | Scanned/garbled PDFs |
| Configuration | PyYAML | Load `config.yaml` |
| Data processing | pandas | DataFrame operations, CSV I/O |
| Web server | Flask | API endpoints, HTML serving |
| Charts | Chart.js 4.x | Trend line charts |
| Frontend | Vanilla JS + CSS | No framework dependencies |

---

## Processing Pipeline

The pipeline runs in three sequential stages. Each reads the previous stage's output and writes a CSV file. Only Stage 1 touches the PDF files; Stages 2 and 3 work purely on CSV data.

### Stage 1 — Raw Extraction

**Function:** `run_stage1(data_dir, progress_cb)`
**Output:** `cache/stage1_raw.csv`

```
For each PDF in ./data/:
  ┌──────────────────────┐
  │ Parse filename        │──▶ Extract date + report name
  │ (yyyy-mm-dd_Name.pdf)│    from filename pattern
  └──────────┬───────────┘
             │
             ▼
  ┌──────────────────────┐     ┌──────────────────────┐
  │ Skip report?         │─YES─▶ Skip (ECG, MRI, etc.) │
  │ (skip_report_types)  │     └──────────────────────┘
  └──────────┬───────────┘
             │ NO
             ▼
  ┌──────────────────────┐
  │ Extract text         │──▶ pdfplumber → OCR fallback
  │ (pdfplumber / OCR)   │    (see PDF Text Extraction)
  └──────────┬───────────┘
             │
             ▼
  ┌──────────────────────┐
  │ Detect lab name      │──▶ Regex match on first 1500 chars
  │ (lab_patterns)       │    → "Lal PathLabs, Pune" etc.
  └──────────┬───────────┘
             │
             ▼
  ┌──────────────────────┐
  │ Parse every line     │──▶ Regex extracts:
  │ (parse_raw_value_line)│   raw_name, value, unit, ref_range
  └──────────┬───────────┘
             │
             ▼
  ┌──────────────────────┐
  │ Write to CSV         │──▶ stage1_raw.csv
  └──────────────────────┘
```

**Stage 1 output columns:**

| Column | Example | Description |
|--------|---------|-------------|
| `date` | 2024-08-16 | Report date from filename |
| `report_name` | Liver & Renal & TSH | Report name from filename |
| `filename` | 2024-08-16_Liver & Renal & TSH.pdf | Full filename |
| `lab_name` | Lal PathLabs, Pune | Detected lab |
| `raw_name` | TSH Ultrasensitive (TSH) | Test name exactly as printed |
| `value` | 1.99 | Numeric value |
| `unit` | ylU/mL | Unit as extracted (may be garbled) |
| `reference_range` | 0.27 - 4.2 | Reference range string |

> **Key point:** Stage 1 stores **everything** as-is — no filtering of unrecognized tests, no unit corrections. This makes it invaluable for debugging.

---

### Stage 2 — Processing & Normalization

**Function:** `run_stage2(df_raw)`
**Input:** `cache/stage1_raw.csv`
**Output:** `cache/stage2_processed.csv`

```
For each row in stage1_raw.csv:
  ┌──────────────────────────┐
  │ Normalize test name       │──▶ raw_name → canonical test_name
  │ (_normalize_raw_name)     │    using test_name_aliases
  └──────────┬────────────────┘
             │
             ▼
  ┌──────────────────────────┐     ┌────────────────────┐
  │ Alias found?             │─NO──▶ Row DROPPED         │
  │                          │     │ (unrecognized test) │
  └──────────┬───────────────┘     └────────────────────┘
             │ YES
             ▼
  ┌──────────────────────────┐
  │ Unit fix pipeline        │──▶ See "Unit Handling Pipeline"
  │ (5-step process)         │    below for full detail
  └──────────┬───────────────┘
             │
             ▼
  ┌──────────────────────────┐
  │ Write to CSV             │──▶ stage2_processed.csv
  └──────────────────────────┘
```

**Stage 2 adds the `test_name` column** (canonical name) alongside `raw_name`:

| raw_name | test_name |
|----------|-----------|
| TSH Ultrasensitive (TSH) | TSH |
| T3, Total | T3 |
| ACTH - Adreno Corticotropic | ACTH |
| THYROID STIMULATING HORMONE (TSH): | TSH |
| CORTISOL, MORNING, SERUM | Cortisol |
| Glycated Hemoglobin (HbA1C), by HPLC | HbA1C |

**Row count drops** because unrecognized raw names are filtered out:
- Stage 1: ~2,450 rows (all parseable lines)
- Stage 2: ~940 rows (only recognized medical tests)

---

### Stage 3 — Categorization

**Function:** `run_stage3(df_processed)`
**Input:** `cache/stage2_processed.csv`
**Output:** `cache/stage3_categorized.csv`

```
For each row in stage2_processed.csv:
  ┌──────────────────────────┐
  │ Look up category          │──▶ test_name → category
  │ (test_categories config)  │    e.g., "TSH" → "Thyroid"
  └──────────┬────────────────┘
             │
             ▼
  ┌──────────────────────────┐
  │ Write to CSV              │──▶ stage3_categorized.csv
  └──────────────────────────┘
```

**Stage 3 adds the `category` column.** All API endpoints read from this file.

| Category | Tests |
|----------|-------|
| Lipid Profile | Total Cholesterol, Triglycerides, HDL, LDL, VLDL, Non-HDL, Ratios |
| Blood Sugar | Fasting Blood Glucose, HbA1C, eAG |
| Complete Blood Count | Hemoglobin, RBC, WBC, Platelet Count, MCV, MCH, ESR, etc. |
| Differential Count | Neutrophils %, Lymphocytes %, Monocytes %, Eosinophils %, Basophils % |
| Liver Function | SGOT, SGPT, GGTP, ALP, Bilirubin, Protein, Albumin, Globulin |
| Kidney Function | Creatinine, eGFR, Urea, BUN, Uric Acid |
| Electrolytes & Minerals | Sodium, Potassium, Chloride, Calcium, Phosphorus |
| Thyroid | TSH, T3, T4, Free T3, Free T4 |
| Iron & Vitamins | Iron, TIBC, Ferritin, Vitamin D, Vitamin B12 |
| Hormones | ACTH, Cortisol, Insulin Fasting |
| Inflammation & Cardiac | CRP, hs-CRP, Troponin I, LDH, PT, INR |
| Absolute WBC Counts | Neutrophils (Absolute), Lymphocytes (Absolute), etc. |
| Other | Tests not listed in any category |

---

## PDF Text Extraction

The system handles two types of PDFs:

```
                    ┌──────────────┐
                    │ Open PDF with │
                    │  pdfplumber   │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │ Text found?   │
                    │ Not garbled?  │
                    └──┬────────┬──┘
                   YES │        │ NO
                       ▼        ▼
              ┌────────────┐  ┌───────────────────┐
              │ Use native │  │ OCR fallback       │
              │ text       │  │ pdf2image (300dpi) │
              └────────────┘  │ + pytesseract      │
                              └───────────────────┘
```

**Garbled text detection:** If the first 500 characters contain more than 3 hex sequences of 32+ characters (like `0A1B2C3D...`), the text is considered garbled and OCR is triggered.

**Known labs and their PDF types:**

| Lab | PDF Type | Notes |
|-----|----------|-------|
| Lal PathLabs, Pune | Native text | Clean formatting, 2+ space separation |
| Kokilaben Hospital, Mumbai | Native text | Uses em-dashes, pipes, `_ .` artifacts, `-H`/`-L` flags |
| SRL Diagnostics | Native text | No-space names ("TSH3RDGENERATION"), unit after ref range |
| Aarogyamm Pathology, Pune | Native text | Standard formatting |
| Sancheti Hospital, Pune | Native text | Uses soft-hyphen in ref ranges |
| Dr. Nagar Pathology, Ujjain | Scanned (OCR) | Garbled units, sparse formatting |
| Agarwal Diagnostics, Ujjain | Scanned (OCR) | Older handwritten-style reports |

---

## Line-Level Parsing

Each line of extracted text is parsed by `parse_raw_value_line()`:

```
Input line:  "T3, Total 0.57 ng/mL 0.40 - 1.81"

Step 1: Clean OCR artifacts
  - Replace em-dash (—) with space
  - Remove pipes (|), stray dashes before numbers
  - Collapse triple+ spaces

Step 2: Regex match
  ┌───────────────────┐    ┌───────┐    ┌──────────────────┐
  │    test name       │    │ value │    │     rest          │
  │   "T3, Total"      │    │ 0.57  │    │ "ng/mL 0.40-1.81"│
  └───────────────────┘    └───────┘    └──────────────────┘

Step 3: Parse "rest" for unit and reference range
  - Try UNIT_PATTERN at start of rest   → "ng/mL"
  - Remainder is reference range        → "0.40 - 1.81"
  - If no unit at start, try UNIT_TAIL_PATTERN at end

Step 4: Strip duplicate units from reference range
```

**Two regex strategies (tried in order):**

| Pattern | Separator | Used when |
|---------|-----------|-----------|
| `LINE_PATTERN` | 2+ spaces between name and value | Clean native PDFs |
| `LINE_PATTERN_SINGLE` | 1+ spaces | OCR output (single-space separated) |

**Lines that are skipped:**
- Lines shorter than 5 characters
- Lines matching any keyword in `skip_line_keywords` (headers, footers, notes, doctor names, etc.)
- Lines where regex doesn't match the `name value rest` pattern

---

## Unit Handling Pipeline

Stage 2 applies five transforms to each row's unit, in this exact order:

```
Raw unit from Stage 1
        │
        ▼
┌─────────────────────────────────┐
│ 1. OCR Fix                      │  "ylU/mL" → "µIU/mL"
│    (ocr_unit_fixes)             │  "ng/db"  → "ng/dL"
└───────────────┬─────────────────┘
                ▼
┌─────────────────────────────────┐
│ 2. Per-Test Override            │  Cortisol: "g/dL" → "µg/dL"
│    (unit_overrides)             │  (OCR drops µ prefix)
└───────────────┬─────────────────┘
                ▼
┌─────────────────────────────────┐
│ 3. Infer Missing Unit           │  If unit is empty,
│    (unit_inference)             │  assign default for test
└───────────────┬─────────────────┘
                ▼
┌─────────────────────────────────┐
│ 4. Display Normalization        │  "mg/dl"  → "mg/dL"
│    (unit_display_normalization) │  "gm/dL"  → "g/dL"
│    Cosmetic only, no value      │  "uIU/mL" → "µIU/mL"
│    change                       │  "mcg/dL" → "µg/dL"
└───────────────┬─────────────────┘
                ▼
┌─────────────────────────────────┐
│ 5. Value Conversion             │  T3: ng/dL × 0.01 → ng/mL
│    (unit_conversions)           │  (SRL uses ng/dL, others ng/mL)
│    Changes BOTH value and unit  │
└───────────────┬─────────────────┘
                ▼
        Final unit + value
```

**Why this order matters:** OCR fixes must happen first so subsequent steps see clean unit strings. Display normalization must happen before conversion so the `from` field in `unit_conversions` matches consistently.

---

## Configuration Reference

All user-configurable data lives in `config.yaml`. The pipeline reads it once on startup and caches it. Clicking "Refresh Data" reloads the config.

| Section | Purpose | Used in |
|---------|---------|---------|
| `skip_report_types` | Report names to ignore (ECG, MRI, etc.) | Stage 1 |
| `test_name_aliases` | Raw name → canonical name mapping (~240 entries) | Stage 2 |
| `unit_inference` | Default unit per canonical test name | Stage 2 |
| `ocr_unit_fixes` | Garbled OCR unit → correct unit | Stage 2 |
| `unit_overrides` | Per-test wrong unit → correct unit | Stage 2 |
| `unit_display_normalization` | Cosmetic unit unification | Stage 2 |
| `unit_conversions` | Value scaling across different unit systems | Stage 2 |
| `known_units` | Set of recognized unit strings for parsing | Stage 1 |
| `skip_line_keywords` | Line-level skip keywords (~50 entries) | Stage 1 |
| `method_indicators` | Lab method names to strip from test names | Stage 2 |
| `lab_patterns` | Regex → lab name mapping (9 labs) | Stage 1 |
| `test_categories` | Groups tests into UI categories (12 groups) | Stage 3 |

---

## API Reference

All endpoints read from `cache/stage3_categorized.csv`.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Serves the dashboard HTML |
| `/api/data` | GET | All records with test list, dates, reports |
| `/api/trend/<test_name>` | GET | Time-series data for one test (dates, values, units, refs, labs) |
| `/api/summary` | GET | Statistics: test count, record count, date range |
| `/api/config/categories` | GET | Test category groupings from config |
| `/api/refresh` | POST | Start background re-processing of all PDFs |
| `/api/refresh/status` | GET | Polling endpoint for refresh progress |

### Background Refresh Flow

```
Browser                     Flask Server               Background Thread
   │                            │                            │
   │──POST /api/refresh────────▶│                            │
   │                            │──spawn thread─────────────▶│
   │◀─{"status":"started"}──────│                            │
   │                            │                     reload config
   │                            │                     clear cache
   │──GET /api/refresh/status──▶│                            │
   │◀─{current:5,total:167}─────│◀───progress callback───────│
   │                            │                     run Stage 1
   │──GET /api/refresh/status──▶│                     run Stage 2
   │◀─{current:100,total:167}───│                     run Stage 3
   │          ...               │                            │
   │──GET /api/refresh/status──▶│                            │
   │◀─{done:true}───────────────│◀──────done─────────────────│
   │                            │                            │
   │──reload page──────────────▶│                            │
```

---

## Frontend Architecture

The dashboard has three views, switchable via tabs:

```
┌─────────────────────────────────────────────────────┐
│  Header: Title + Date Range + [Refresh Data]        │
├─────────────────────────────────────────────────────┤
│  Stats Bar: Unique Tests │ Total Readings │ PDFs    │
├─────────────────────────────────────────────────────┤
│  Filters: Test dropdown │ Date range │ Search       │
├────────────┬──────────────┬─────────────────────────┤
│  Tab: Table │ Tab: Trends │ Tab: Pivot View         │
├────────────┴──────────────┴─────────────────────────┤
│                                                     │
│  [Active View Content]                              │
│                                                     │
│  Table View:    Sortable, paginated data table      │
│  Trends View:   Chart.js line chart + stats         │
│  Pivot View:    Latest values grouped by category   │
│                                                     │
└─────────────────────────────────────────────────────┘
```

### Data Flow

```
Page Load
    │
    ├──▶ GET /api/config/categories  ──▶ TEST_CATEGORIES (for grouping)
    │
    ├──▶ GET /api/data               ──▶ allRecords[] (table + pivot)
    │
    └──▶ GET /api/summary            ──▶ Stats bar numbers
```

### Value Classification

Values are color-coded by comparing against the reference range:

| Color | Meaning | Logic |
|-------|---------|-------|
| Green | Normal | Value is within low–high range |
| Amber | Low | Value < lower limit |
| Red | High | Value > upper limit |
| Default | Unknown | No parseable reference range |

---

## Cache Files

| File | Rows | Columns | Size | Stage |
|------|------|---------|------|-------|
| `stage1_raw.csv` | ~2,450 | 9 | ~320KB | All parseable value lines from all PDFs |
| `stage2_processed.csv` | ~940 | 9 | ~110KB | Recognized tests only, units normalized |
| `stage3_categorized.csv` | ~940 | 10 | ~125KB | Same + `category` column |

**Selective re-processing:**

| Scenario | Delete | What re-runs |
|----------|--------|--------------|
| Added new PDFs | All 3 files | Full pipeline (~4 min, OCR-heavy) |
| Edited `test_name_aliases`, `unit_*` config | stage2 + stage3 | Stages 2+3 only (instant) |
| Edited `test_categories` | stage3 only | Stage 3 only (instant) |
| Edited `lab_patterns`, `skip_line_keywords` | All 3 files | Full pipeline |

---

## Adding Support for a New Lab

### Step 1: Identify the lab

```bash
# Extract text from a sample PDF
python3 -c "
from pdf_processor import extract_text_from_pdf
print(extract_text_from_pdf('./data/your_file.pdf')[:2000])
"
```

Look at the header for the lab name/address.

### Step 2: Add lab detection pattern

In `config.yaml` under `lab_patterns`:

```yaml
- pattern: "Unique\\s+Text\\s+From\\s+Header"
  name: "Lab Name, City"
```

### Step 3: Check what raw names this lab uses

After a full refresh, search `cache/stage1_raw.csv` for rows from the new lab. Look at the `raw_name` column for test names that aren't yet in `test_name_aliases`.

### Step 4: Add missing aliases

In `config.yaml` under `test_name_aliases`:

```yaml
new raw name: Canonical Test Name
```

### Step 5: Handle unit quirks

- If the lab's OCR produces garbled units → add to `ocr_unit_fixes`
- If it uses a different unit scale → add to `unit_conversions`
- If OCR drops characters from units → add to `unit_overrides`

### Step 6: Re-process

Delete `cache/stage2_processed.csv` and `cache/stage3_categorized.csv`, then refresh. Stage 1 data is reused.

---

## Troubleshooting

### A test is missing from the dashboard

1. **Check Stage 1:** Open `cache/stage1_raw.csv` and search for the test. If it's there with a `raw_name`, the line parser found it but Stage 2 filtered it (alias missing).

2. **Check Stage 2:** If the raw name is in Stage 1 but not in `cache/stage2_processed.csv`, add the raw name (lowercase) to `test_name_aliases` in `config.yaml`.

3. **Not in Stage 1:** The line-level parser didn't match. Test the exact line:
   ```python
   from pdf_processor import parse_raw_value_line
   result = parse_raw_value_line("exact line from PDF")
   print(result)  # None means no match
   ```

### A test has wrong units on the trend chart

Check both `stage1_raw.csv` (raw unit) and `stage2_processed.csv` (processed unit) to see where the unit went wrong. Add corrections to the appropriate config section.

### Values from one lab are wildly different

The lab likely reports in a different unit scale. Compare values + units from `stage2_processed.csv`, then add a `unit_conversions` entry:

```yaml
unit_conversions:
  TestName:
    - from: ng/dL       # the lab's unit
      to: ng/mL         # the standard unit
      factor: 0.01      # multiply value by this
```

### OCR produces unreadable text

Some very old or low-quality scanned PDFs produce unusable OCR output. These appear in Stage 1 with garbled `raw_name` values and are naturally filtered out in Stage 2. This is expected behavior.

### Refresh takes too long

Stage 1 (PDF extraction + OCR) takes ~4 minutes for ~170 PDFs. Stages 2 and 3 are instant. The progress bar in the UI shows real-time file-by-file progress. To skip re-extraction, only delete Stage 2+3 cache files.

# Medical Report Dashboard

A web application that reads PDF blood reports, extracts test results using text parsing and OCR (for scanned documents), and presents them in a consolidated, interactive dashboard.

## Features

- **PDF Processing**: Reads all `yyyy-mm-dd_<name>.pdf` files from the `./data` folder
- **Smart Text Extraction**: Uses `pdfplumber` for native PDF text; falls back to OCR (`pytesseract` + `pdf2image`) for scanned or garbled PDFs
- **69 Test Types Recognized**: Lipid Profile, CBC, LFT, KFT, Thyroid, HbA1C, Electrolytes, Iron Studies, Vitamins, Hormones, and more
- **Consolidated Table**: Sortable, paginated table of all extracted results
- **Trend Charts**: Interactive line charts showing any test parameter over time with reference range bands
- **Pivot View**: Latest values grouped by medical category with color-coded normal/abnormal indicators
- **Caching**: Processed results are cached in `./cache/results.csv` for fast subsequent loads

## Prerequisites

- Python 3.8+
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) installed (`brew install tesseract` on macOS)
- [Poppler](https://poppler.freedesktop.org/) for PDF-to-image conversion (`brew install poppler` on macOS)

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
source venv/bin/activate
python app.py
```

Open http://127.0.0.1:5000 in your browser.

### Refresh Data

Click the "Refresh Data" button in the dashboard header to re-process all PDFs (useful after adding new reports to `./data`).

## Project Structure

```
medicalReportCharter/
├── data/                  # PDF blood reports (yyyy-mm-dd_Name.pdf)
├── cache/                 # Cached extraction results
├── app.py                 # Flask web application
├── pdf_processor.py       # PDF text extraction, OCR, and result parsing
├── templates/
│   └── index.html         # Dashboard HTML
├── static/
│   ├── css/style.css      # Styles
│   └── js/app.js          # Frontend logic
├── requirements.txt       # Python dependencies
└── README.md
```

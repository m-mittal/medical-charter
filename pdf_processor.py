"""
Three-stage PDF processing pipeline.

Stage 1 (extract)  — Read PDFs, extract raw values as-is      → stage1_raw.csv
Stage 2 (process)  — Normalize names, fix/convert units        → stage2_processed.csv
Stage 3 (categorize) — Assign test categories for the UI       → stage3_categorized.csv
"""

import os
import re
import logging
from datetime import datetime
from pathlib import Path

import pdfplumber
import pytesseract
import yaml
from pdf2image import convert_from_path
import pandas as pd

logger = logging.getLogger(__name__)

CACHE_DIR = Path('./cache')
STAGE1_FILE = CACHE_DIR / 'stage1_raw.csv'
STAGE2_FILE = CACHE_DIR / 'stage2_processed.csv'
STAGE3_FILE = CACHE_DIR / 'stage3_categorized.csv'
SYNCED_FILES = CACHE_DIR / 'synced_files.json'

STAGE1_COLUMNS = [
    'date', 'report_name', 'filename', 'lab_name',
    'raw_name', 'value', 'unit', 'reference_range',
]
STAGE2_COLUMNS = STAGE1_COLUMNS + ['test_name']
STAGE3_COLUMNS = STAGE2_COLUMNS + ['category']


# ===========================================================================
# Config loading
# ===========================================================================

_CONFIG_PATH = Path(__file__).parent / 'config.yaml'
_config_cache = None


def _load_config():
    global _config_cache
    if _config_cache is None:
        with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
            _config_cache = yaml.safe_load(f)
        _compile_config(_config_cache)
    return _config_cache


def _compile_config(cfg):
    """Pre-compile regex patterns and derived structures from raw config."""
    cfg['_lab_patterns_compiled'] = [
        (re.compile(entry['pattern'], re.IGNORECASE), entry['name'])
        for entry in cfg.get('lab_patterns', [])
    ]

    indicators = '|'.join(re.escape(m) for m in cfg.get('method_indicators', []))
    cfg['_method_re'] = re.compile(
        rf'\(.*?({indicators}).*?\)', re.IGNORECASE
    ) if indicators else None

    cfg['_known_units_set'] = {u.lower() for u in cfg.get('known_units', [])}

    norm = cfg.get('unit_display_normalization', {})
    cfg['_unit_display_map'] = {k.lower(): v for k, v in norm.items()}

    aliases = cfg.get('test_name_aliases', {})
    for key, val in list(aliases.items()):
        if val is None:
            aliases[key] = None

    # Build reverse lookup: category for each test name
    categories = cfg.get('test_categories', {})
    cat_lookup = {}
    for cat, tests in categories.items():
        for t in tests:
            cat_lookup[t] = cat
    cfg['_category_lookup'] = cat_lookup


def get_config():
    return _load_config()


def reload_config():
    """Force reload of config from disk."""
    global _config_cache
    _config_cache = None
    return _load_config()


# ===========================================================================
# Shared helpers
# ===========================================================================

def parse_filename(filepath: str):
    """Extract date and report type from filename like yyyy-mm-dd_Name.pdf"""
    basename = Path(filepath).stem
    match = re.match(r'(\d{4}-\d{2}-\d{2})\s*(?:to\s*\d{2}-\d{2})?\s*_(.+)', basename)
    if match:
        date_str = match.group(1)
        report_name = match.group(2).strip()
        try:
            report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            report_date = None
        return report_date, report_name
    return None, basename


def should_skip_report(report_name: str) -> bool:
    cfg = get_config()
    name_lower = report_name.lower().strip()
    return any(skip in name_lower for skip in cfg.get('skip_report_types', []))


GARBLED_HEX_PATTERN = re.compile(r'[0-9A-F]{32,}', re.IGNORECASE)


def is_text_garbled(text: str) -> bool:
    if not text:
        return True
    return len(GARBLED_HEX_PATTERN.findall(text[:500])) > 3


def extract_text_from_pdf(filepath: str) -> str:
    """Extract text from PDF, falling back to OCR if needed."""
    text_pages = []
    needs_ocr = False

    try:
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text and not is_text_garbled(page_text):
                    text_pages.append(page_text)
                else:
                    needs_ocr = True
                    break
    except Exception as e:
        logger.warning(f"pdfplumber failed for {filepath}: {e}")
        needs_ocr = True

    if needs_ocr:
        text_pages = []
        try:
            images = convert_from_path(filepath, dpi=300)
            for img in images:
                page_text = pytesseract.image_to_string(img)
                if page_text:
                    text_pages.append(page_text)
        except Exception as e:
            logger.error(f"OCR failed for {filepath}: {e}")
            return ""

    return "\n".join(text_pages)


def detect_lab_name(text: str) -> str:
    cfg = get_config()
    header = text[:1500]
    for pattern, lab_name in cfg['_lab_patterns_compiled']:
        if pattern.search(header):
            return lab_name
    return 'Unknown Lab'


# ===========================================================================
# Line-level parsing (shared by Stage 1)
# ===========================================================================

LINE_PATTERN = re.compile(
    r'^(?P<name>[A-Za-z\*#][A-Za-z0-9\s\-\.\(\)/:,%&\+\*#]+?)\s{2,}'
    r'(?P<value>\d+\.?\d*)\s*'
    r'(?P<rest>.*)$'
)

LINE_PATTERN_SINGLE = re.compile(
    r'^(?P<name>[A-Za-z\*#][A-Za-z0-9\s\-\.\(\)/,:&%]+?)\s+'
    r'(?P<value>\d+\.?\d*)\s*'
    r'(?P<rest>.*)$'
)

UNIT_PATTERN = re.compile(
    r'^(?P<unit>mg/dL|mg/dl|g/dL|g/dl|gm/dL|%|U/L|u/l|mEq/L|mIU/L|'
    r'uIU/mL|μIU/mL|µIU/mL|ng/mL|ng/dl|ng/dL|pg/mL|fL|fl|pg|thou/mm3|'
    r'mill/mm3|mm/hr|mL/min/1\.73m2|seconds|sec|mcg/dL|mcg/dl|'
    r'umol/L|ug/dL|μg/dL|µg/dL|cells/cumm|lakhs/cumm|mg/L|IU/mL|'
    r'nmol/L|pmol/L|lakh/cumm|thou/cumm|mill/cumm|g/L|U/mL|mm3|'
    r'[yp][lWw]?[Il1]?U/m[Ll]|ulU/m[Ll]|pIU/m[Ll]|ng/db)',
    re.IGNORECASE
)

UNIT_TAIL_PATTERN = re.compile(
    r'(mg/dL|g/dL|g/dl|%|U/L|u/l|mEq/L|mIU/L|µ?IU/mL|uIU/mL|'
    r'ng/mL|ng/dL|ng/dl|pg/mL|fL|fl|pg|thou/mm3|mill/mm3|mm/hr|'
    r'mcg/dL|ug/dL|µg/dL|µg/dl|cells/cumm|mg/L|IU/mL|nmol/L|'
    r'pmol/L|mm3|[yp][lWw]?[Il1]?U/m[Ll]|ulU/m[Ll]|pIU/m[Ll]|ng/db)[\s.]*$',
    re.IGNORECASE
)


def _clean_ocr_line(line: str) -> str:
    """Remove common OCR artifacts before parsing."""
    line = line.replace('\u2014', ' ').replace('\u2013', ' ')
    line = line.replace('|', ' ')
    line = re.sub(r'(?<=[A-Za-z):])\s*_\s*\.?\s*(?=\d)', '  ', line)
    line = re.sub(r'(?<=\s)-(?=\d+\.?\d*)', '', line)
    line = re.sub(r'[=]\s*o(?=pg/|ng/|ug/|µg/|mg/)', '', line, flags=re.IGNORECASE)
    line = re.sub(r'\s{3,}', '  ', line)
    return line.strip()


def _extract_unit_from_ref(ref: str):
    """Try to pull unit off the end of the reference range string."""
    m = UNIT_TAIL_PATTERN.search(ref)
    if m:
        unit = m.group(1)
        cleaned_ref = ref[:m.start()].strip().rstrip(',').strip()
        return unit, cleaned_ref
    return None, ref


def parse_raw_value_line(line: str):
    """
    Stage-1 parser: extract raw_name, value, unit, reference_range from a line.
    No name normalization — returns the raw test name as printed in the PDF.
    """
    cfg = get_config()
    known_units = cfg.get('_known_units_set', set())

    line = _clean_ocr_line(line)

    m = LINE_PATTERN.match(line)
    if not m:
        m = LINE_PATTERN_SINGLE.match(line)
    if not m:
        return None

    raw_name = m.group('name').strip()
    value_str = m.group('value')
    rest = m.group('rest').strip()

    # Strip -H (High) / -L (Low) flags
    rest = re.sub(r'^-[HL]\b\s*', '', rest).strip()

    try:
        value = float(value_str)
    except ValueError:
        return None

    unit = ''
    ref = rest

    if rest:
        unit_match = UNIT_PATTERN.match(rest)
        if unit_match:
            unit = unit_match.group('unit')
            ref = rest[unit_match.end():].strip()
        else:
            tokens = rest.split()
            if tokens and tokens[0].lower() in known_units:
                unit = tokens[0]
                ref = ' '.join(tokens[1:])
            elif tokens:
                first = tokens[0]
                if re.match(r'^\d+\.?\d*$', first):
                    ref = rest
                    unit = ''
                elif first.lower() in ('high', 'low', 'normal', 'desirable:',
                                       'borderline', 'optimal', 'adult', 'to'):
                    ref = rest
                    unit = ''

    if not unit:
        extracted_unit, cleaned_ref = _extract_unit_from_ref(ref)
        if extracted_unit:
            unit = extracted_unit
            ref = cleaned_ref

    if unit:
        ref = re.sub(re.escape(unit) + r'[\s.]*$', '', ref, flags=re.IGNORECASE).strip()
        ref = ref.rstrip('.,; ')

    return {
        'raw_name': raw_name,
        'value': value,
        'unit': unit.strip(),
        'reference_range': ref.strip(),
    }


def extract_raw_results(text: str) -> list:
    """Stage-1 text parser: extract all parseable value lines from PDF text."""
    cfg = get_config()
    skip_keywords = cfg.get('skip_line_keywords', [])

    results = []
    lines = text.split('\n')
    in_absolute_section = False

    for line in lines:
        line = line.strip()
        if not line or len(line) < 5:
            continue

        line_lower = line.lower()

        if 'absolute leucocyte count' in line_lower or 'absolute leukocyte count' in line_lower:
            in_absolute_section = True
            continue
        if in_absolute_section and any(kw in line_lower for kw in [
            'platelet', 'e.s.r', 'esr', 'mean platelet', 'comment', 'note'
        ]):
            in_absolute_section = False

        if any(kw in line_lower for kw in skip_keywords):
            continue

        parsed = parse_raw_value_line(line)
        if parsed:
            parsed['_in_absolute_section'] = in_absolute_section
            results.append(parsed)

    return results


# ===========================================================================
# STAGE 1 — Raw extraction
# ===========================================================================

def run_stage1(data_dir: str = './data', progress_cb=None) -> pd.DataFrame:
    """
    Read all PDFs and extract raw values as-is.
    No name normalization, no unit conversion.
    Saves → stage1_raw.csv
    """
    all_rows = []
    files = sorted(Path(data_dir).glob('*.pdf'))
    total = len(files)

    for idx, filepath in enumerate(files):
        if progress_cb:
            progress_cb(idx + 1, total, filepath.name)

        report_date, report_name = parse_filename(str(filepath))
        if not report_date:
            logger.warning(f"Skipping {filepath.name}: could not parse date")
            continue
        if should_skip_report(report_name):
            logger.info(f"Skipping non-blood-test report: {filepath.name}")
            continue

        logger.info(f"[{idx+1}/{total}] Extracting: {filepath.name}")
        text = extract_text_from_pdf(str(filepath))
        if not text:
            logger.warning(f"No text extracted from {filepath.name}")
            continue

        lab_name = detect_lab_name(text)
        raw_results = extract_raw_results(text)
        if not raw_results:
            logger.warning(f"No values parsed from {filepath.name}")
            continue

        for r in raw_results:
            all_rows.append({
                'date': report_date.isoformat(),
                'report_name': report_name,
                'filename': filepath.name,
                'lab_name': lab_name,
                'raw_name': r['raw_name'],
                'value': r['value'],
                'unit': r['unit'],
                'reference_range': r['reference_range'],
                '_in_absolute_section': r['_in_absolute_section'],
            })

        logger.info(f"  -> {len(raw_results)} raw values from {lab_name}")

    if not all_rows:
        return pd.DataFrame(columns=STAGE1_COLUMNS + ['_in_absolute_section'])

    df = pd.DataFrame(all_rows)
    df['date'] = pd.to_datetime(df['date']).dt.date
    df = df.sort_values(['date', 'raw_name']).reset_index(drop=True)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(STAGE1_FILE, index=False)
    logger.info(f"Stage 1 complete: {len(df)} raw rows → {STAGE1_FILE}")
    return df


# ===========================================================================
# STAGE 2 — Normalize names, fix & convert units
# ===========================================================================

def _normalize_raw_name(name: str) -> str:
    """Clean a raw test name for alias lookup (lowercase, strip method info)."""
    cfg = get_config()
    aliases = cfg.get('test_name_aliases', {})

    cleaned = name.strip().lower()
    cleaned = re.sub(r'\s+', ' ', cleaned)

    method_re = cfg.get('_method_re')
    if method_re:
        cleaned = method_re.sub('', cleaned).strip()

    cleaned = re.sub(r',\s*by\s+\w+$', '', cleaned).strip()
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    cleaned = re.sub(r'^[\*#\s]+', '', cleaned).strip()

    result = aliases.get(cleaned)
    if result is not None:
        return result
    if result is None and cleaned in aliases:
        return None

    cleaned2 = cleaned.rstrip('.,;:*')
    result2 = aliases.get(cleaned2)
    if result2 is not None:
        return result2
    if result2 is None and cleaned2 in aliases:
        return None

    return None


def _fix_ocr_unit(unit: str) -> str:
    cfg = get_config()
    fixes = cfg.get('ocr_unit_fixes', {})
    return fixes.get(unit.lower().rstrip('.'), unit)


def run_stage2(df_raw: pd.DataFrame = None) -> pd.DataFrame:
    """
    Normalize test names, fix OCR units, apply conversions.
    Reads stage1_raw.csv if no DataFrame passed.
    Saves → stage2_processed.csv
    """
    cfg = get_config()
    unit_overrides = cfg.get('unit_overrides', {})
    unit_inference = cfg.get('unit_inference', {})
    display_map = cfg.get('_unit_display_map', {})
    conversions = cfg.get('unit_conversions', {})

    if df_raw is None:
        df_raw = pd.read_csv(STAGE1_FILE)
        df_raw['date'] = pd.to_datetime(df_raw['date']).dt.date

    rows = []
    for _, r in df_raw.iterrows():
        # --- Name normalization ---
        test_name = _normalize_raw_name(r['raw_name'])
        if not test_name:
            continue

        # Disambiguate absolute WBC counts
        in_abs = r.get('_in_absolute_section', False)
        if in_abs and test_name.endswith('%'):
            test_name = test_name.replace(' %', ' (Absolute)')

        value = float(r['value'])
        unit = str(r['unit']) if pd.notna(r['unit']) else ''

        # --- OCR unit fix ---
        unit = _fix_ocr_unit(unit)

        # --- Per-test unit override (e.g. Cortisol g/dL → µg/dL) ---
        test_ov = unit_overrides.get(test_name, {})
        if unit in test_ov:
            unit = test_ov[unit]

        # --- Infer unit when missing ---
        if not unit and test_name in unit_inference:
            unit = unit_inference[test_name]

        # --- Display normalization (cosmetic) ---
        if unit:
            unit = display_map.get(unit.lower(), unit)

        # --- Value conversion (e.g. T3 ng/dL → ng/mL) ---
        if test_name in conversions:
            for conv in conversions[test_name]:
                if unit == conv['from'] or display_map.get(unit.lower()) == conv['from']:
                    value = round(value * conv['factor'], 4)
                    unit = conv['to']
                    break

        rows.append({
            'date': r['date'],
            'report_name': r['report_name'],
            'filename': r['filename'],
            'lab_name': r['lab_name'],
            'raw_name': r['raw_name'],
            'test_name': test_name,
            'value': value,
            'unit': unit,
            'reference_range': r['reference_range'] if pd.notna(r['reference_range']) else '',
        })

    if not rows:
        return pd.DataFrame(columns=STAGE2_COLUMNS)

    df = pd.DataFrame(rows)
    df = df.sort_values(['date', 'test_name']).reset_index(drop=True)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(STAGE2_FILE, index=False)
    logger.info(f"Stage 2 complete: {len(df)} processed rows → {STAGE2_FILE}")
    return df


# ===========================================================================
# STAGE 3 — Categorize for the UI
# ===========================================================================

def run_stage3(df_processed: pd.DataFrame = None) -> pd.DataFrame:
    """
    Assign a category to each test row.
    Reads stage2_processed.csv if no DataFrame passed.
    Saves → stage3_categorized.csv
    """
    cfg = get_config()
    cat_lookup = cfg.get('_category_lookup', {})

    if df_processed is None:
        df_processed = pd.read_csv(STAGE2_FILE)
        df_processed['date'] = pd.to_datetime(df_processed['date']).dt.date

    df = df_processed.copy()
    df['category'] = df['test_name'].map(lambda t: cat_lookup.get(t, 'Other'))
    df = df.sort_values(['category', 'test_name', 'date']).reset_index(drop=True)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(STAGE3_FILE, index=False)
    logger.info(f"Stage 3 complete: {len(df)} categorized rows → {STAGE3_FILE}")
    return df


# ===========================================================================
# Full pipeline
# ===========================================================================

def run_full_pipeline(data_dir: str = './data', progress_cb=None) -> pd.DataFrame:
    """Run all three stages sequentially."""
    df1 = run_stage1(data_dir, progress_cb=progress_cb)
    df2 = run_stage2(df1)
    df3 = run_stage3(df2)
    return df3


def get_processed_filenames() -> set:
    """Return all filenames we've already attempted (processed + skipped)."""
    import json
    names = set()
    if STAGE3_FILE.exists():
        df = pd.read_csv(STAGE3_FILE, usecols=['filename'])
        names.update(df['filename'].unique())
    if SYNCED_FILES.exists():
        names.update(json.loads(SYNCED_FILES.read_text()))
    return names


def save_synced_filenames(filenames: set):
    """Persist the set of all attempted filenames so they aren't re-downloaded."""
    import json
    existing = set()
    if SYNCED_FILES.exists():
        existing = set(json.loads(SYNCED_FILES.read_text()))
    existing.update(filenames)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    SYNCED_FILES.write_text(json.dumps(sorted(existing)))


def get_cached_or_process(data_dir: str = './data') -> pd.DataFrame:
    """Return stage-3 data from cache, or run full pipeline."""
    if STAGE3_FILE.exists():
        df = pd.read_csv(STAGE3_FILE)
        df['date'] = pd.to_datetime(df['date']).dt.date
        return df
    return run_full_pipeline(data_dir)


def run_incremental_pipeline(data_dir: str = './data', progress_cb=None) -> pd.DataFrame:
    """
    Process only NEW PDFs (not already in stage3) and merge with existing data.

    Returns the merged stage-3 DataFrame. If no new PDFs are found,
    returns the existing data unchanged.
    """
    existing_df = pd.DataFrame(columns=STAGE3_COLUMNS)
    if STAGE3_FILE.exists():
        existing_df = pd.read_csv(STAGE3_FILE)
        existing_df['date'] = pd.to_datetime(existing_df['date']).dt.date

    processed_filenames = set(existing_df['filename'].unique()) if not existing_df.empty else set()

    known_filenames = get_processed_filenames()

    all_pdfs = sorted(Path(data_dir).glob('*.pdf'))
    new_pdfs = [f for f in all_pdfs if f.name not in known_filenames]

    if not new_pdfs:
        logger.info("No new PDFs to process")
        return existing_df

    logger.info(f"Incremental: {len(new_pdfs)} new PDF(s) out of {len(all_pdfs)} total")

    all_rows = []
    total = len(new_pdfs)
    for idx, filepath in enumerate(new_pdfs):
        if progress_cb:
            progress_cb(idx + 1, total, filepath.name)

        report_date, report_name = parse_filename(str(filepath))
        if not report_date:
            logger.warning(f"Skipping {filepath.name}: could not parse date")
            continue
        if should_skip_report(report_name):
            logger.info(f"Skipping non-blood-test report: {filepath.name}")
            continue

        logger.info(f"[{idx+1}/{total}] Extracting: {filepath.name}")
        text = extract_text_from_pdf(str(filepath))
        if not text:
            logger.warning(f"No text extracted from {filepath.name}")
            continue

        lab_name = detect_lab_name(text)
        raw_results = extract_raw_results(text)
        if not raw_results:
            logger.warning(f"No values parsed from {filepath.name}")
            continue

        for r in raw_results:
            all_rows.append({
                'date': report_date.isoformat(),
                'report_name': report_name,
                'filename': filepath.name,
                'lab_name': lab_name,
                'raw_name': r['raw_name'],
                'value': r['value'],
                'unit': r['unit'],
                'reference_range': r['reference_range'],
                '_in_absolute_section': r['_in_absolute_section'],
            })

        logger.info(f"  -> {len(raw_results)} raw values from {lab_name}")

    attempted_names = {f.name for f in new_pdfs}
    save_synced_filenames(attempted_names)

    if not all_rows:
        logger.info("No new values extracted — returning existing data")
        return existing_df

    df_new_raw = pd.DataFrame(all_rows)
    df_new_raw['date'] = pd.to_datetime(df_new_raw['date']).dt.date

    df_new_s2 = run_stage2(df_new_raw)
    df_new_s3 = run_stage3(df_new_s2)

    merged = pd.concat([existing_df, df_new_s3], ignore_index=True)
    merged = merged.sort_values(['category', 'test_name', 'date']).reset_index(drop=True)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    merged.to_csv(STAGE3_FILE, index=False)
    logger.info(f"Incremental merge complete: {len(df_new_s3)} new + {len(existing_df)} existing = {len(merged)} total rows")
    return merged


def clear_cache():
    """Remove all stage files."""
    for f in [STAGE1_FILE, STAGE2_FILE, STAGE3_FILE]:
        if f.exists():
            f.unlink()

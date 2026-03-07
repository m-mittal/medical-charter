"""
Export the dashboard as a single self-contained HTML file.

Usage:
    python export.py              # uses cached data (fast)
    python export.py --refresh    # re-process all PDFs first

The output file can be shared via WhatsApp, AirDrop, email, etc.
Recipients open it in any phone/desktop browser — no server needed.
"""

import argparse
import json
import html
from pathlib import Path
from datetime import date

import pandas as pd

from pdf_processor import (
    get_cached_or_process, run_full_pipeline, reload_config,
    clear_cache, get_config, STAGE3_FILE,
)

OUTPUT_DIR = Path('./dist')
STATIC_DIR = Path('./static')
TEMPLATES_DIR = Path('./templates')

CHARTJS_CDN = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js'


def build_api_data(df: pd.DataFrame) -> dict:
    """Replicate what /api/data returns."""
    df = df.copy()
    df['date'] = df['date'].astype(str)
    df = df.fillna('')
    return {
        'records': df.to_dict(orient='records'),
        'tests': sorted(df['test_name'].unique().tolist()),
        'dates': sorted(df['date'].unique().tolist()),
        'reports': sorted(df['report_name'].unique().tolist()),
    }


def build_summary(df: pd.DataFrame) -> dict:
    """Replicate what /api/summary returns."""
    df = df.copy()
    df['date'] = df['date'].astype(str)
    df = df.fillna('')

    latest_date = df['date'].max()
    latest = df[df['date'] == latest_date]

    test_groups = {}
    for _, row in df.iterrows():
        tn = row['test_name']
        if tn not in test_groups:
            test_groups[tn] = {'first_date': row['date'], 'last_date': row['date'], 'count': 0}
        test_groups[tn]['last_date'] = max(test_groups[tn]['last_date'], row['date'])
        test_groups[tn]['first_date'] = min(test_groups[tn]['first_date'], row['date'])
        test_groups[tn]['count'] += 1

    return {
        'latest_records': latest.to_dict(orient='records'),
        'test_count': df['test_name'].nunique(),
        'record_count': len(df),
        'date_range': f"{df['date'].min()} to {df['date'].max()}",
        'file_count': df['filename'].nunique(),
        'test_groups': test_groups,
    }


def build_trends(df: pd.DataFrame) -> dict:
    """Pre-compute trend data for every test (replicate /api/trend/<name>)."""
    df = df.copy()
    df['date'] = df['date'].astype(str)
    df = df.fillna('')

    trends = {}
    for test_name in df['test_name'].unique():
        filtered = df[df['test_name'] == test_name].sort_values('date')
        unit = filtered['unit'].iloc[0] if not filtered['unit'].empty else ''
        trends[test_name] = {
            'dates': filtered['date'].tolist(),
            'values': filtered['value'].tolist(),
            'units': unit if unit else '',
            'refs': filtered['reference_range'].tolist(),
            'labs': filtered['lab_name'].tolist(),
        }
    return trends


def export_html(df: pd.DataFrame, output_path: Path):
    """Generate a self-contained HTML file with all data embedded."""
    api_data = build_api_data(df)
    summary = build_summary(df)
    cfg = get_config()
    categories = cfg.get('test_categories', {})
    trends = build_trends(df)

    css = (STATIC_DIR / 'css' / 'style.css').read_text(encoding='utf-8')
    js = (STATIC_DIR / 'js' / 'app.js').read_text(encoding='utf-8')

    generated_date = date.today().isoformat()

    page = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Medical Report Dashboard</title>
    <style>
{css}
    </style>
    <script src="{CHARTJS_CDN}"></script>
</head>
<body>
    <header>
        <div class="header-content">
            <h1>Medical Report Dashboard</h1>
            <p class="subtitle" id="dateRange">Loading...</p>
        </div>
        <div class="header-actions">
            <button id="refreshBtn" class="btn btn-primary" title="Re-scan all PDFs and rebuild data">
                <span class="btn-icon">&#8635;</span> Refresh Data
            </button>
        </div>
    </header>

    <div id="loading" class="loading-overlay">
        <div class="spinner"></div>
        <p>Loading report data...</p>
        <div class="progress-bar-container" id="progressBarContainer" style="display:none;">
            <div class="progress-bar" id="progressBar"></div>
        </div>
    </div>

    <main>
        <section class="stats-bar" id="statsBar">
            <div class="stat-card">
                <div class="stat-value" id="statTests">-</div>
                <div class="stat-label">Unique Tests</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" id="statRecords">-</div>
                <div class="stat-label">Total Readings</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" id="statFiles">-</div>
                <div class="stat-label">PDF Reports</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" id="statDates">-</div>
                <div class="stat-label">Test Dates</div>
            </div>
        </section>

        <section class="controls">
            <button class="filter-toggle" id="filterToggle">
                <span class="toggle-icon">&#9660;</span> Filters &amp; Search
            </button>
            <div class="filter-body" id="filterBody">
                <div class="filter-group">
                    <label for="testFilter">Filter by Test</label>
                    <select id="testFilter" multiple>
                        <option value="">All Tests</option>
                    </select>
                </div>
                <div class="filter-group">
                    <label for="dateFrom">From</label>
                    <input type="date" id="dateFrom">
                </div>
                <div class="filter-group">
                    <label for="dateTo">To</label>
                    <input type="date" id="dateTo">
                </div>
                <div class="filter-group">
                    <label for="searchBox">Search</label>
                    <input type="text" id="searchBox" placeholder="Search test name...">
                </div>
                <div class="filter-group filter-actions">
                    <button id="applyFilters" class="btn btn-secondary">Apply</button>
                    <button id="clearFilters" class="btn btn-outline">Clear</button>
                </div>
            </div>
        </section>

        <section class="view-tabs">
            <button class="tab active" data-view="table">Consolidated Table</button>
            <button class="tab" data-view="trends">Trend Charts</button>
            <button class="tab" data-view="pivot">Pivot View</button>
        </section>

        <section id="tableView" class="view active">
            <div class="table-wrapper">
                <table id="resultsTable">
                    <thead>
                        <tr>
                            <th data-sort="date">Date <span class="sort-icon"></span></th>
                            <th data-sort="test_name">Test Name <span class="sort-icon"></span></th>
                            <th data-sort="value">Value <span class="sort-icon"></span></th>
                            <th>Unit</th>
                            <th>Reference Range</th>
                            <th>Report</th>
                        </tr>
                    </thead>
                    <tbody id="tableBody"></tbody>
                </table>
            </div>
            <div class="pagination" id="pagination"></div>
        </section>

        <section id="trendsView" class="view">
            <div class="trend-selector">
                <label for="trendTest">Select Test for Trend:</label>
                <select id="trendTest"></select>
            </div>
            <div class="chart-container">
                <canvas id="trendChart"></canvas>
            </div>
            <div class="trend-stats" id="trendStats"></div>
        </section>

        <section id="pivotView" class="view">
            <p class="pivot-help">This view shows the latest value for each test, grouped by category. Click any test name to see its trend.</p>
            <div id="pivotContent"></div>
        </section>
    </main>

    <footer>
        <p>Medical Report Dashboard &mdash; Exported on {generated_date}</p>
    </footer>

    <script>
// Embedded data for offline/static mode
window.__STATIC_DATA__ = {json.dumps(api_data, default=str)};
window.__STATIC_SUMMARY__ = {json.dumps(summary, default=str)};
window.__STATIC_CATEGORIES__ = {json.dumps(categories, default=str)};
window.__STATIC_TRENDS__ = {json.dumps(trends, default=str)};
    </script>
    <script>
{js}
    </script>
</body>
</html>'''

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(page, encoding='utf-8')
    size_kb = output_path.stat().st_size / 1024
    print(f"\nExported to: {output_path}")
    print(f"File size:   {size_kb:.0f} KB")
    print(f"Records:     {len(api_data['records'])}")
    print(f"Tests:       {len(api_data['tests'])}")
    print(f"Date range:  {summary['date_range']}")
    print(f"\nShare this file via WhatsApp, AirDrop, or email.")
    print("Recipients open it in any browser — no server needed.")


def main():
    parser = argparse.ArgumentParser(description='Export dashboard as a standalone HTML file')
    parser.add_argument('--refresh', action='store_true',
                        help='Re-process all PDFs before exporting')
    parser.add_argument('-o', '--output', default='dist/dashboard.html',
                        help='Output file path (default: dist/dashboard.html)')
    args = parser.parse_args()

    if args.refresh:
        print("Re-processing all PDFs...")
        reload_config()
        clear_cache()
        df = run_full_pipeline('./data')
    else:
        print("Loading from cache...")
        df = get_cached_or_process('./data')

    if df.empty:
        print("No data found. Run with --refresh or add PDFs to ./data/")
        return

    export_html(df, Path(args.output))


if __name__ == '__main__':
    main()

import logging
import os
import threading
from pathlib import Path

from flask import Flask, jsonify, render_template
import pandas as pd

from pdf_processor import (
    get_cached_or_process, run_full_pipeline, clear_cache,
    get_config, reload_config, STAGE3_FILE,
)
from dropbox_sync import sync_from_dropbox

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

DATA_DIR = './data'
DROPBOX_FOLDER = os.environ.get('DROPBOX_FOLDER', '/')

# ---------------------------------------------------------------------------
# Background refresh state
# ---------------------------------------------------------------------------

refresh_state = {
    'running': False,
    'current': 0,
    'total': 0,
    'current_file': '',
    'stage': '',
    'done': False,
    'error': None,
}
refresh_lock = threading.Lock()


def _progress_cb(current, total, filename):
    with refresh_lock:
        refresh_state['current'] = current
        refresh_state['total'] = total
        refresh_state['current_file'] = filename
        refresh_state['stage'] = 'extracting'


def run_refresh_in_background():
    global refresh_state
    try:
        reload_config()

        with refresh_lock:
            refresh_state['stage'] = 'syncing'
        sync_from_dropbox(DATA_DIR, DROPBOX_FOLDER)

        clear_cache()

        with refresh_lock:
            refresh_state['stage'] = 'extracting'

        run_full_pipeline(DATA_DIR, progress_cb=_progress_cb)

        with refresh_lock:
            refresh_state['running'] = False
            refresh_state['done'] = True
            refresh_state['error'] = None

    except Exception as e:
        logger.error(f"Refresh failed: {e}")
        with refresh_lock:
            refresh_state['running'] = False
            refresh_state['done'] = True
            refresh_state['error'] = str(e)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data() -> pd.DataFrame:
    return get_cached_or_process(DATA_DIR)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/data')
def get_data():
    df = load_data()
    if df.empty:
        return jsonify({'records': [], 'tests': [], 'dates': [], 'reports': []})

    df['date'] = df['date'].astype(str)
    df = df.fillna('')

    return jsonify({
        'records': df.to_dict(orient='records'),
        'tests': sorted(df['test_name'].unique().tolist()),
        'dates': sorted(df['date'].unique().tolist()),
        'reports': sorted(df['report_name'].unique().tolist()),
    })


@app.route('/api/trend/<test_name>')
def get_trend(test_name):
    df = load_data()
    if df.empty:
        return jsonify({'dates': [], 'values': [], 'units': '', 'refs': [], 'labs': []})

    df['date'] = df['date'].astype(str)
    df = df.fillna('')
    filtered = df[df['test_name'] == test_name].sort_values('date')

    if filtered.empty:
        return jsonify({'dates': [], 'values': [], 'units': '', 'refs': [], 'labs': []})

    unit = filtered['unit'].iloc[0] if not filtered['unit'].empty else ''

    return jsonify({
        'dates': filtered['date'].tolist(),
        'values': filtered['value'].tolist(),
        'units': unit if unit else '',
        'refs': filtered['reference_range'].tolist(),
        'labs': filtered['lab_name'].tolist(),
    })


@app.route('/api/refresh', methods=['POST'])
def refresh_data():
    global refresh_state
    with refresh_lock:
        if refresh_state['running']:
            return jsonify({'status': 'already_running'})
        refresh_state = {
            'running': True,
            'current': 0,
            'total': 0,
            'current_file': '',
            'stage': '',
            'done': False,
            'error': None,
        }

    thread = threading.Thread(target=run_refresh_in_background, daemon=True)
    thread.start()
    return jsonify({'status': 'started'})


@app.route('/api/refresh/status')
def refresh_status():
    with refresh_lock:
        return jsonify(refresh_state.copy())


@app.route('/api/sync', methods=['POST'])
def sync_dropbox():
    """Pull new PDFs from Dropbox without reprocessing the pipeline."""
    result = sync_from_dropbox(DATA_DIR, DROPBOX_FOLDER)
    return jsonify(result)


@app.route('/api/config/categories')
def get_categories():
    cfg = get_config()
    return jsonify(cfg.get('test_categories', {}))


@app.route('/api/summary')
def get_summary():
    df = load_data()
    if df.empty:
        return jsonify({'latest': {}, 'test_count': 0, 'date_range': ''})

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

    return jsonify({
        'latest_records': latest.to_dict(orient='records'),
        'test_count': df['test_name'].nunique(),
        'record_count': len(df),
        'date_range': f"{df['date'].min()} to {df['date'].max()}",
        'file_count': df['filename'].nunique(),
        'test_groups': test_groups,
    })


if __name__ == '__main__':
    app.run(debug=True, port=5000)

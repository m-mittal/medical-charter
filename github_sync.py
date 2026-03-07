"""
Push updated cache files to GitHub via the Contents API.

Requires two environment variables:
    GITHUB_TOKEN  — personal access token with contents:write scope
    GITHUB_REPO   — owner/repo  (e.g. mohitmi/medicalReportCharter)

If either is missing, the push is silently skipped.
"""

import base64
import json
import logging
import os
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

logger = logging.getLogger(__name__)

API_BASE = 'https://api.github.com'


def _get_config():
    token = os.environ.get('GITHUB_TOKEN')
    repo = os.environ.get('GITHUB_REPO')
    if not token or not repo:
        return None, None
    return token, repo


def push_file_to_github(local_path: str, repo_path: str, message: str) -> bool:
    """
    Upload a local file to the GitHub repo at *repo_path*.

    Uses the Contents API (PUT /repos/{owner}/{repo}/contents/{path}).
    Fetches the current file's SHA first so it can be updated in place.
    Returns True on success.
    """
    token, repo = _get_config()
    if not token or not repo:
        logger.info("GitHub credentials not configured — skipping push")
        return False

    file_data = Path(local_path)
    if not file_data.exists():
        logger.warning(f"Cannot push {local_path}: file not found")
        return False

    content_b64 = base64.b64encode(file_data.read_bytes()).decode('ascii')

    url = f"{API_BASE}/repos/{repo}/contents/{repo_path}"
    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json',
    }

    sha = None
    try:
        req = Request(url, headers=headers, method='GET')
        with urlopen(req) as resp:
            existing = json.loads(resp.read().decode())
            sha = existing.get('sha')
    except HTTPError as e:
        if e.code != 404:
            logger.error(f"GitHub GET failed: {e.code} {e.reason}")
            return False

    payload = {
        'message': message,
        'content': content_b64,
    }
    if sha:
        payload['sha'] = sha

    try:
        data = json.dumps(payload).encode()
        req = Request(url, data=data, headers=headers, method='PUT')
        with urlopen(req) as resp:
            if resp.status in (200, 201):
                logger.info(f"Pushed {repo_path} to GitHub ({repo})")
                return True
    except HTTPError as e:
        body = e.read().decode() if e.fp else ''
        logger.error(f"GitHub PUT failed: {e.code} {e.reason} — {body}")
    except Exception as e:
        logger.error(f"GitHub push error: {e}")

    return False


def push_stage3_to_github() -> bool:
    """Push the stage3_categorized.csv to the repo."""
    from pdf_processor import STAGE3_FILE
    return push_file_to_github(
        str(STAGE3_FILE),
        'cache/stage3_categorized.csv',
        'Update stage3 data from Render refresh',
    )

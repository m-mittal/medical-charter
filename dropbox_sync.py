"""
Sync PDF files from a Dropbox folder to the local data/ directory.

Requires three environment variables:
    DROPBOX_APP_KEY
    DROPBOX_APP_SECRET
    DROPBOX_REFRESH_TOKEN

If any are missing, sync is silently skipped so local dev works unchanged.
"""

import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _get_client():
    """Build an authenticated Dropbox client, or return None if creds are missing."""
    app_key = os.environ.get('DROPBOX_APP_KEY')
    app_secret = os.environ.get('DROPBOX_APP_SECRET')
    refresh_token = os.environ.get('DROPBOX_REFRESH_TOKEN')

    if not all([app_key, app_secret, refresh_token]):
        return None

    import dropbox
    return dropbox.Dropbox(
        app_key=app_key,
        app_secret=app_secret,
        oauth2_refresh_token=refresh_token,
    )


def sync_from_dropbox(
    local_dir: str = './data',
    dropbox_folder: str = '/MedicalReports',
) -> dict:
    """
    Download new/changed PDFs from *dropbox_folder* into *local_dir*.

    Skips files that already exist locally with the same size.
    Returns a summary dict with counts of synced, skipped, and total files.
    """
    dbx = _get_client()
    if dbx is None:
        logger.info("Dropbox credentials not configured — skipping sync")
        return {'synced': 0, 'skipped': 0, 'total': 0}

    local_path = Path(local_dir)
    local_path.mkdir(parents=True, exist_ok=True)

    folder = dropbox_folder.rstrip('/')
    synced = 0
    skipped = 0

    try:
        import dropbox as dbx_module

        result = dbx.files_list_folder(folder)
        entries = list(result.entries)

        while result.has_more:
            result = dbx.files_list_folder_continue(result.cursor)
            entries.extend(result.entries)

        pdf_entries = [
            e for e in entries
            if isinstance(e, dbx_module.files.FileMetadata)
            and e.name.lower().endswith('.pdf')
        ]

        logger.info(f"Dropbox: found {len(pdf_entries)} PDF(s) in {folder}")

        for entry in pdf_entries:
            dest = local_path / entry.name
            if dest.exists() and dest.stat().st_size == entry.size:
                skipped += 1
                continue

            logger.info(f"Downloading: {entry.name} ({entry.size:,} bytes)")
            dbx.files_download_to_file(str(dest), entry.path_lower)
            synced += 1

    except dbx_module.exceptions.AuthError:
        logger.error("Dropbox auth failed — check your credentials")
    except dbx_module.exceptions.ApiError as e:
        logger.error(f"Dropbox API error: {e}")
    except Exception as e:
        logger.error(f"Dropbox sync error: {e}")

    total = synced + skipped
    logger.info(f"Dropbox sync done: {synced} downloaded, {skipped} skipped, {total} total")
    return {'synced': synced, 'skipped': skipped, 'total': total}

"""
Google Drive backup — the "Log in with Google Drive" flow.

OAuth 2.0 installed-app flow, reusing whatever Google account the user is
signed into in their browser:

  1. POST /drive/login/start  — build the authorize URL, open the browser.
  2. GET  /drive/callback     — Google redirects back with a one-time code;
                                we exchange it for tokens and store the
                                refresh token (a durable credential).
  3. GET  /drive/status       — the UI polls this to learn when it connected.
  4. POST /drive/backup       — ensure a ``voicebox`` folder exists in Drive,
                                then mirror captures/ and generations/ into it.
  5. POST /drive/disconnect   — forget the refresh token locally.

The ``state`` we mint and round-trip prevents login-CSRF, mirroring the old
Voicebox Cloud pairing. The refresh token lives in the local app database;
once the user has authorized, the app can back up forever without re-auth.
"""

import logging
import secrets
import time
import webbrowser
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from .. import config
from ..database import DriveSettings as DBDriveSettings

logger = logging.getLogger(__name__)

SINGLETON_ID = 1
PENDING_TTL_SECONDS = 600  # the whole browser flow must finish within 10 min

# state -> expiry epoch. In-memory: a single backend process owns the flow, and a
# dropped pairing should simply be restarted.
_pending: dict[str, float] = {}

# Drive API scope: app-created files only (least privilege).
SCOPES = "https://www.googleapis.com/auth/drive.file"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_API = "https://www.googleapis.com/drive/v3"
UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
ROOT_FOLDER_NAME = "voicebox"


def _prune() -> None:
    now = time.time()
    for state, expiry in list(_pending.items()):
        if expiry < now:
            _pending.pop(state, None)


def _json_dict(response: httpx.Response) -> dict | None:
    """Parsed JSON body, or None when it isn't a JSON object."""
    try:
        payload = response.json()
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def _consume_state(state: str) -> bool:
    """Validate and single-use-consume a pending state."""
    _prune()
    expiry = _pending.pop(state, None)
    return expiry is not None and expiry >= time.time()


def _credentials_error() -> tuple[bool, str]:
    """Return a friendly message when OAuth credentials are missing."""
    creds_file = config.get_google_credentials_file()
    return (
        False,
        "Google OAuth credentials are not configured. Create an OAuth Client ID "
        f"in Google Cloud Console and save {{'client_id': '…', 'client_secret': '…'}} "
        f"to {creds_file} (or set GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET).",
    )


def start_login(callback_url: str, device_name: str) -> str:
    """Mint a state, build the authorize URL, and open the browser.

    Returns the authorize URL (also opened here) so the caller can surface it as
    a fallback if the browser didn't open.
    """
    client_id, _ = config.get_google_credentials()
    if not client_id:
        raise RuntimeError("GOOGLE_CLIENT_ID is not configured")

    state = secrets.token_urlsafe(24)
    _prune()
    _pending[state] = time.time() + PENDING_TTL_SECONDS

    params = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": callback_url,
            "response_type": "code",
            "scope": SCOPES,
            "access_type": "offline",  # returns a refresh token
            "prompt": "consent",  # guarantees a refresh token every time
            "state": state,
        }
    )
    authorize_url = f"{AUTH_URL}?{params}"

    try:
        webbrowser.open(authorize_url)
    except Exception:  # pragma: no cover - platform dependent
        logger.exception("failed to open browser for google drive login")

    return authorize_url


async def handle_callback(db: Session, code: str, state: str) -> tuple[bool, str]:
    """Exchange the code for tokens and store the refresh token."""
    if not _consume_state(state):
        return False, "This sign-in link is invalid or has expired. Start again from the app."
    if not code:
        return False, "Missing authorization code."

    client_id, client_secret = config.get_google_credentials()
    if not client_id or not client_secret:
        ok, message = _credentials_error()
        return ok, message

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            token_resp = await client.post(
                TOKEN_URL,
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": "http://127.0.0.1:17493/drive/callback",
                    "grant_type": "authorization_code",
                },
            )
            if token_resp.status_code != 200:
                logger.warning("google token exchange failed: %s", token_resp.status_code)
                return False, "Google rejected the sign-in code. Try again."
            token = _json_dict(token_resp)
            if token is None:
                return False, "Google returned an unexpected response."
            refresh_token = token.get("refresh_token")
            access_token = token.get("access_token")
            if not refresh_token or not access_token:
                return False, "Google did not return a refresh token."

            # Best-effort: fetch the account email for display.
            account_email = None
            try:
                who = await client.get(
                    f"{DRIVE_API}/about",
                    params={"fields": "user"},
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                user = _json_dict(who).get("user", {}) if _json_dict(who) else {}
                account_email = user.get("emailAddress") if isinstance(user, dict) else None
            except httpx.HTTPError:
                logger.exception("failed to fetch google account email")
    except httpx.HTTPError:
        logger.exception("network error during google token exchange")
        return False, "Could not reach Google. Check your connection and try again."

    _store_tokens(
        db,
        refresh_token=refresh_token,
        access_token=access_token,
        expires_in=token.get("expires_in", 3600),
        account_email=account_email,
    )
    logger.info("connected to Google Drive as %r", account_email)
    return True, "Connected"


def _get_or_create_row(db: Session) -> DBDriveSettings:
    from sqlalchemy.exc import IntegrityError

    row = db.query(DBDriveSettings).filter(DBDriveSettings.id == SINGLETON_ID).first()
    if row is None:
        row = DBDriveSettings(id=SINGLETON_ID)
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            row = db.query(DBDriveSettings).filter(DBDriveSettings.id == SINGLETON_ID).one()
        else:
            db.refresh(row)
    return row


def _store_tokens(
    db: Session,
    *,
    refresh_token: str,
    access_token: str,
    expires_in: int,
    account_email: str | None,
) -> None:
    from datetime import datetime, timedelta

    row = _get_or_create_row(db)
    row.refresh_token = refresh_token
    row.access_token = access_token
    row.token_expires_at = datetime.utcnow() + timedelta(seconds=max(expires_in - 60, 60))
    row.account_email = account_email
    row.connected_at = datetime.utcnow()
    db.commit()


def get_status(db: Session) -> dict:
    """Local view of the Drive link — never returns tokens."""
    row = _get_or_create_row(db)
    connected = bool(row.refresh_token)
    client_id, _ = config.get_google_credentials()
    return {
        "connected": connected,
        "account_email": row.account_email if connected else None,
        "connected_at": row.connected_at if connected else None,
        "last_backup_at": row.last_backup_at if connected else None,
        "folder_name": ROOT_FOLDER_NAME,
        "credentials_configured": bool(client_id),
    }


def save_credentials(client_id: str, client_secret: str) -> dict:
    """Persist OAuth credentials from the UI and report the new status."""
    if not client_id or not client_secret:
        raise RuntimeError("Both the Client ID and Client Secret are required.")
    config.save_google_credentials(client_id.strip(), client_secret.strip())
    logger.info("saved google drive OAuth credentials via UI")
    return {"credentials_configured": True}


def disconnect(db: Session) -> None:
    """Forget the local credential. Revoking server-side is up to the user."""
    row = _get_or_create_row(db)
    row.refresh_token = None
    row.access_token = None
    row.token_expires_at = None
    row.account_email = None
    row.root_folder_id = None
    row.last_backup_at = None
    db.commit()


async def _access_token(db: Session) -> str | None:
    """Return a fresh access token, refreshing if expired/absent."""
    from datetime import datetime, timedelta

    row = _get_or_create_row(db)
    if not row.refresh_token:
        return None

    now = datetime.utcnow()
    if row.access_token and row.token_expires_at and row.token_expires_at > now:
        return row.access_token

    client_id, client_secret = config.get_google_credentials()
    if not client_id or not client_secret:
        return None

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": row.refresh_token,
                "grant_type": "refresh_token",
            },
        )
        if resp.status_code != 200:
            logger.warning("google refresh failed: %s", resp.status_code)
            return None
        token = _json_dict(resp)
        if token is None:
            return None
        access_token = token.get("access_token")
        if not access_token:
            return None
        row.access_token = access_token
        row.token_expires_at = datetime.utcnow() + timedelta(
            seconds=max(int(token.get("expires_in", 3600)) - 60, 60)
        )
        db.commit()
        return access_token


async def _ensure_folder(client: httpx.AsyncClient, access_token: str, name: str, parent_id: str | None) -> str:
    """Find or create a folder with the given name, returning its id."""
    safe_name = name.replace("\\", "\\\\").replace("'", "\\'")
    query = f"name='{safe_name}' and mimeType='application/vnd.google-apps.folder'"
    if parent_id:
        query += f" and '{parent_id}' in parents and trashed=false"
    else:
        query += " and 'root' in parents and trashed=false"

    found = await client.get(
        f"{DRIVE_API}/files",
        params={"q": query, "fields": "files(id,name)"},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if found.status_code == 200:
        files = _json_dict(found).get("files", []) if _json_dict(found) else []
        if files:
            return files[0]["id"]

    created = await client.post(
        f"{DRIVE_API}/files",
        params={"fields": "id,name"},
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json={"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id] if parent_id else []},
    )
    payload = _json_dict(created)
    if created.status_code != 200 or payload is None:
        logger.warning("google folder create failed: %s", created.status_code)
        raise RuntimeError("Could not create the 'voicebox' folder in Google Drive.")
    return payload["id"]


async def _upload_file(client: httpx.AsyncClient, access_token: str, path, parent_id: str):
    """Upload a single file, skipping it if an identical name+size already exists.

    Returns ``(status, file_id)`` where status is ``"uploaded"`` (new file),
    ``"skipped"`` (identical name+size already present) or ``None`` (failure).
    """
    import json
    from pathlib import Path

    path = Path(path)
    size = path.stat().st_size
    name = path.name

    query = f"name='{name.replace(chr(92), chr(92) * 2).replace(chr(39), chr(92) + chr(39))}' and '{parent_id}' in parents and trashed=false"
    existing = await client.get(
        f"{DRIVE_API}/files",
        params={"q": query, "fields": "files(id,name,size)"},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if existing.status_code == 200:
        files = _json_dict(existing).get("files", []) if _json_dict(existing) else []
        for f in files:
            if str(f.get("size", "")) == str(size):
                return "skipped", f["id"]  # already backed up

    metadata = json.dumps({"name": name, "parents": [parent_id]})
    with open(path, "rb") as fh:
        upload = await client.post(
            f"{UPLOAD_URL}?uploadType=multipart",
            headers={"Authorization": f"Bearer {access_token}"},
            files={
                "metadata": (None, metadata, "application/json"),
                "file": (name, fh, "application/octet-stream"),
            },
        )
    payload = _json_dict(upload)
    if upload.status_code not in (200, 201) or payload is None:
        logger.warning("google upload failed for %s: %s", name, upload.status_code)
        return None, None
    return "uploaded", payload.get("id")


async def run_backup(db: Session) -> dict:
    """Ensure the voicebox folder exists, then mirror captures/ and generations/."""
    from datetime import datetime

    access_token = await _access_token(db)
    if not access_token:
        return {
            "success": False,
            "message": "Not connected to Google Drive. Log in first.",
            "uploaded": 0,
            "skipped": 0,
        }

    row = _get_or_create_row(db)
    uploads = {"captures": 0, "generations": 0}
    skipped = {"captures": 0, "generations": 0}

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            root_id = row.root_folder_id or await _ensure_folder(client, access_token, ROOT_FOLDER_NAME, None)
            row.root_folder_id = root_id

            sources = [
                ("captures", config.get_captures_dir()),
                ("generations", config.get_generations_dir()),
            ]
            for label, folder in sources:
                if not folder.is_dir():
                    continue
                sub_id = await _ensure_folder(client, access_token, label, root_id)
                for path in sorted(folder.rglob("*")):
                    if not path.is_file():
                        continue
                    # Keep relative sub-structure inside the Drive subfolder.
                    rel = path.relative_to(folder)
                    if len(rel.parts) > 1:
                        parent = sub_id
                        for part in rel.parts[:-1]:
                            parent = await _ensure_folder(client, access_token, part, parent)
                    else:
                        parent = sub_id
                    result, _ = await _upload_file(client, access_token, path, parent)
                    if result == "uploaded":
                        uploads[label] += 1
                    else:
                        skipped[label] += 1
        except RuntimeError as exc:
            logger.exception("drive backup failed")
            return {"success": False, "message": str(exc), "uploaded": 0, "skipped": 0}

    row.last_backup_at = datetime.utcnow()
    db.commit()

    total = uploads["captures"] + uploads["generations"]
    total_skipped = skipped["captures"] + skipped["generations"]
    message = f"Backup complete — {total} file(s) uploaded, {total_skipped} unchanged."
    logger.info("drive backup: %s", message)
    return {
        "success": True,
        "message": message,
        "uploaded": total,
        "skipped": total_skipped,
    }
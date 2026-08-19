"""Google Drive backup routes — the "Log in with Google Drive" flow.

The browser-based OAuth pairing flow:
  1. POST /drive/login/start  — opens the browser to Google's authorize page
                                (uses whatever Google account the browser is
                                already signed into; prompts if none).
  2. GET  /drive/callback     — the browser lands here with a one-time code;
                                the backend exchanges it for tokens.
  3. GET  /drive/status       — the UI polls this to learn when it connected.
  4. POST /drive/backup       — ensure a ``voicebox`` folder exists in Drive,
                                then mirror captures/ and generations/ into it.
  5. POST /drive/disconnect   — forget the local refresh token.
"""

import socket

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..services import drive as drive_service

router = APIRouter(prefix="/drive", tags=["drive"])

GOOGLE_REDIRECT = "http://127.0.0.1:17493/drive/callback"


def _callback_url(request: Request) -> str:
    port = request.url.port or 17493
    return f"http://127.0.0.1:{port}/drive/callback"


@router.post("/login/start", response_model=models.DriveLoginStartResponse)
async def start_drive_login(request: Request):
    device_name = socket.gethostname() or "Desktop"
    try:
        authorize_url = drive_service.start_login(_callback_url(request), device_name)
    except RuntimeError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    return models.DriveLoginStartResponse(authorize_url=authorize_url)


@router.get("/callback", response_class=HTMLResponse)
async def drive_callback(
    request: Request,
    code: str = "",
    state: str = "",
    db: Session = Depends(get_db),
):
    ok, message = await drive_service.handle_callback(db, code=code, state=state)
    heading = "You're connected" if ok else "Couldn't connect"
    accent = "#16a34a" if ok else "#dc2626"
    sub = (
        "Google Drive is now linked. Return to the app — your captures and "
        "generations will be backed up to the 'voicebox' folder."
        if ok
        else message
    )
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Google Drive</title>
<style>
  body {{ margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
    font-family: ui-sans-serif, system-ui, -apple-system, sans-serif; background:#0b0b0d; color:#e7e7ea; }}
  .card {{ max-width:28rem; padding:2.5rem; text-align:center; }}
  h1 {{ font-size:1.5rem; margin:0 0 .5rem; color:{accent}; }}
  p {{ color:#a1a1aa; line-height:1.5; word-break:break-word; }}
</style></head>
<body><div class="card"><h1>{heading}</h1><p>{sub}</p></div></body></html>"""
    return HTMLResponse(content=html, status_code=200 if ok else 400)


@router.get("/status", response_model=models.DriveStatusResponse)
async def drive_status(db: Session = Depends(get_db)):
    return models.DriveStatusResponse(**drive_service.get_status(db))


@router.post("/backup", response_model=models.DriveBackupResponse)
async def drive_backup(db: Session = Depends(get_db)):
    return models.DriveBackupResponse(**await drive_service.run_backup(db))


@router.post("/disconnect", response_model=models.DriveStatusResponse)
async def drive_disconnect(db: Session = Depends(get_db)):
    drive_service.disconnect(db)
    return models.DriveStatusResponse(**drive_service.get_status(db))
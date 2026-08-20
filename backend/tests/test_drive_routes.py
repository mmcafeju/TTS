"""
Route-level tests for the Google Drive backup endpoints.

Exercises the HTTP layer (FastAPI router) with the drive service mocked, so no
Google credentials or network access are required.

Usage:
    python -m pytest backend/tests/test_drive_routes.py -v
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent.parent))  # project root → backend package

from backend.database import get_db
from backend.routes.drive import router as drive_router


@pytest.fixture
def client():
    """App with only the drive router and an overridden get_db dependency."""
    app = FastAPI()

    def override_get_db():
        yield None

    app.dependency_overrides[get_db] = override_get_db
    app.include_router(drive_router)
    return TestClient(app)


def test_status_not_connected(client):
    with patch("backend.services.drive.get_status", return_value={
        "connected": False,
        "account_email": None,
        "connected_at": None,
        "last_backup_at": None,
        "folder_name": "voicebox",
    }):
        resp = client.get("/drive/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["connected"] is False
    assert body["folder_name"] == "voicebox"


def test_status_connected(client):
    with patch("backend.services.drive.get_status", return_value={
        "connected": True,
        "account_email": "me@example.com",
        "connected_at": "2026-08-19T00:00:00",
        "last_backup_at": None,
        "folder_name": "voicebox",
    }):
        resp = client.get("/drive/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["connected"] is True
    assert body["account_email"] == "me@example.com"


def test_login_start_returns_url(client):
    with patch("backend.services.drive.start_login", return_value="https://accounts.google.com/o/oauth2/v2/auth?state=abc"):
        resp = client.post("/drive/login/start")
    assert resp.status_code == 200
    assert resp.json()["authorize_url"].startswith("https://accounts.google.com/")


def test_login_start_missing_creds_400(client):
    with patch("backend.services.drive.start_login", side_effect=RuntimeError("GOOGLE_CLIENT_ID is not configured")):
        resp = client.post("/drive/login/start")
    assert resp.status_code == 400
    assert "GOOGLE_CLIENT_ID" in resp.json()["detail"]


def test_disconnect(client):
    with patch("backend.services.drive.disconnect"), \
         patch("backend.services.drive.get_status", return_value={
             "connected": False,
             "account_email": None,
             "connected_at": None,
             "last_backup_at": None,
             "folder_name": "voicebox",
         }):
        resp = client.post("/drive/disconnect")
    assert resp.status_code == 200
    assert resp.json()["connected"] is False


def test_backup_success(client):
    with patch("backend.services.drive.run_backup", return_value={
        "success": True,
        "message": "Backup complete — 3 file(s) uploaded, 0 unchanged.",
        "uploaded": 3,
        "skipped": 0,
    }):
        resp = client.post("/drive/backup")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["uploaded"] == 3


def test_backup_not_connected(client):
    with patch("backend.services.drive.run_backup", return_value={
        "success": False,
        "message": "Not connected to Google Drive. Log in first.",
        "uploaded": 0,
        "skipped": 0,
    }):
        resp = client.post("/drive/backup")
    assert resp.status_code == 200
    assert resp.json()["success"] is False


def test_credentials_save_success(client):
    with patch("backend.services.drive.save_credentials"), \
         patch("backend.services.drive.get_status", return_value={
             "connected": False,
             "account_email": None,
             "connected_at": None,
             "last_backup_at": None,
             "folder_name": "voicebox",
             "credentials_configured": True,
         }):
        resp = client.post("/drive/credentials", json={
            "client_id": "12345.apps.googleusercontent.com",
            "client_secret": "GOCSPX-secret",
        })
    assert resp.status_code == 200
    assert resp.json()["credentials_configured"] is True


def test_credentials_save_missing_400(client):
    with patch("backend.services.drive.save_credentials",
               side_effect=RuntimeError("Both the Client ID and Client Secret are required.")):
        resp = client.post("/drive/credentials", json={"client_id": "", "client_secret": ""})
    assert resp.status_code == 400
    assert "Client ID" in resp.json()["detail"]


def test_callback_success_html(client):
    with patch("backend.services.drive.handle_callback", return_value=(True, "Connected")):
        resp = client.get("/drive/callback", params={"code": "abc", "state": "xyz"})
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "You're connected" in resp.text


def test_callback_failure_html(client):
    with patch("backend.services.drive.handle_callback", return_value=(False, "This sign-in link is invalid or has expired.")):
        resp = client.get("/drive/callback", params={"code": "abc", "state": "xyz"})
    assert resp.status_code == 400
    assert "Couldn't connect" in resp.text
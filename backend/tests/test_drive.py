"""
Tests for the Google Drive backup service (backend/services/drive.py).

Covers the local OAuth state machine, token persistence, and the
upload/skip logic using mocked httpx so no real Google credentials or
network access are required.

Usage:
    python -m pytest backend/tests/test_drive.py -v
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))  # project root → backend package

from backend.database import Base, DriveSettings as DBDriveSettings
from backend.services import drive as drive_service


@pytest.fixture
def test_db():
    """Create a temporary test database with the DriveSettings table."""
    temp_dir = tempfile.mkdtemp()
    db_path = Path(temp_dir) / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    yield db
    db.close()
    engine.dispose()
    for attempt in range(5):
        try:
            shutil.rmtree(temp_dir)
            break
        except PermissionError:
            import time
            time.sleep(0.2)


@pytest.fixture
def mock_creds(monkeypatch):
    """Provide fake Google OAuth credentials."""
    monkeypatch.setattr(
        drive_service.config,
        "get_google_credentials",
        lambda: ("TEST_ID.apps.googleusercontent.com", "TEST_SECRET"),
    )


def _mock_json_response(payload: dict, status: int = 200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload
    return resp


# ── state machine ────────────────────────────────────────────────────────

def test_state_mint_and_consume(test_db, mock_creds):
    url = drive_service.start_login("http://127.0.0.1:17493/drive/callback", "test-pc")
    assert "accounts.google.com/o/oauth2/v2/auth" in url
    assert "client_id=TEST_ID" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fdrive.file" in url
    assert "state=" in url

    state = url.split("state=")[1].split("&")[0]
    assert drive_service._consume_state(state) is True
    # single-use
    assert drive_service._consume_state(state) is False


def test_state_expiry(test_db, mock_creds):
    url = drive_service.start_login("http://127.0.0.1:17493/drive/callback", "test-pc")
    state = url.split("state=")[1].split("&")[0]
    drive_service._pending[state] = 0  # already expired
    assert drive_service._consume_state(state) is False


def test_start_login_missing_creds(test_db):
    with patch.object(drive_service.config, "get_google_credentials", return_value=(None, None)):
        with pytest.raises(RuntimeError, match="GOOGLE_CLIENT_ID is not configured"):
            drive_service.start_login("http://127.0.0.1:17493/drive/callback", "test-pc")


# ── token persistence / status ──────────────────────────────────────────

def test_status_empty(test_db):
    status = drive_service.get_status(test_db)
    assert status["connected"] is False
    assert status["account_email"] is None
    assert status["folder_name"] == "voicebox"


def test_store_and_status(test_db):
    drive_service._store_tokens(
        test_db,
        refresh_token="REFRESH",
        access_token="ACCESS",
        expires_in=3600,
        account_email="me@example.com",
    )
    status = drive_service.get_status(test_db)
    assert status["connected"] is True
    assert status["account_email"] == "me@example.com"
    assert status["connected_at"] is not None


def test_disconnect_clears(test_db):
    drive_service._store_tokens(
        test_db,
        refresh_token="REFRESH",
        access_token="ACCESS",
        expires_in=3600,
        account_email="me@example.com",
    )
    drive_service.disconnect(test_db)
    status = drive_service.get_status(test_db)
    assert status["connected"] is False
    assert status["account_email"] is None


# ── access token reuse / refresh ────────────────────────────────────────

def test_access_token_reuses_fresh(test_db):
    drive_service._store_tokens(
        test_db,
        refresh_token="REFRESH",
        access_token="FRESH",
        expires_in=3600,
        account_email="me@example.com",
    )
    token = _run_async(drive_service._access_token(test_db))
    assert token == "FRESH"


def test_access_token_refreshes_expired(test_db, mock_creds):
    drive_service._store_tokens(
        test_db,
        refresh_token="REFRESH",
        access_token="EXPIRED",
        expires_in=3600,
        account_email="me@example.com",
    )
    from datetime import datetime, timedelta
    row = test_db.query(DBDriveSettings).first()
    row.token_expires_at = datetime.utcnow() - timedelta(minutes=5)
    test_db.commit()

    async def fake_post(*args, **kwargs):
        return _mock_json_response({"access_token": "NEW_TOKEN", "expires_in": 3600})

    with patch("httpx.AsyncClient") as mock_client_cls:
        instance = mock_client_cls.return_value
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        instance.post = fake_post
        token = _run_async(drive_service._access_token(test_db))

    assert token == "NEW_TOKEN"
    row = test_db.query(DBDriveSettings).first()
    assert row.access_token == "NEW_TOKEN"


# ── folder query escaping ───────────────────────────────────────────────

def test_folder_query_escapes_quote():
    client = AsyncMock()
    resp = _mock_json_response({"files": []})
    client.get = AsyncMock(return_value=resp)
    created = _mock_json_response({"id": "folder123", "name": "voicebox"}, status=200)
    client.post = AsyncMock(return_value=created)

    folder_id = _run_async(drive_service._ensure_folder(client, "tok", "vo'ice\\box", None))
    assert folder_id == "folder123"
    query = client.get.call_args.kwargs["params"]["q"]
    assert "vo\\'ice" in query  # quote escaped


# ── upload skip logic ───────────────────────────────────────────────────

def test_upload_skips_identical(test_db, tmp_path):
    f = tmp_path / "same.wav"
    f.write_bytes(b"0123456789")

    client = AsyncMock()
    existing = _mock_json_response({"files": [{"id": "existing-id", "name": "same.wav", "size": "10"}]})
    client.get = AsyncMock(return_value=existing)
    client.post = AsyncMock()  # should not be called

    status, file_id = _run_async(drive_service._upload_file(client, "tok", f, "parent1"))
    assert status == "skipped"
    assert file_id == "existing-id"
    client.post.assert_not_called()


def test_upload_new_file(test_db, tmp_path):
    f = tmp_path / "new.wav"
    f.write_bytes(b"0123456789")

    client = AsyncMock()
    existing = _mock_json_response({"files": []})
    client.get = AsyncMock(return_value=existing)
    uploaded = _mock_json_response({"id": "new-id", "name": "new.wav"}, status=200)
    client.post = AsyncMock(return_value=uploaded)

    status, file_id = _run_async(drive_service._upload_file(client, "tok", f, "parent1"))
    assert status == "uploaded"
    assert file_id == "new-id"
    assert client.post.call_args.kwargs["files"]["metadata"][1] == '{"name": "new.wav", "parents": ["parent1"]}'


# ── run_backup ──────────────────────────────────────────────────────────

def test_run_backup_not_connected(test_db):
    result = _run_async(drive_service.run_backup(test_db))
    assert result["success"] is False
    assert result["uploaded"] == 0


def test_callback_rejects_bad_state(test_db):
    ok, msg = _run_async(drive_service.handle_callback(test_db, code="abc", state="bogus"))
    assert ok is False
    assert "invalid or has expired" in msg


def test_callback_missing_code(test_db, mock_creds):
    drive_service.start_login("http://127.0.0.1:17493/drive/callback", "test-pc")
    state = list(drive_service._pending.keys())[0]
    ok, msg = _run_async(drive_service.handle_callback(test_db, code="", state=state))
    assert ok is False
    assert "Missing authorization code" in msg


def test_callback_token_exchange_and_store(test_db, mock_creds):
    url = drive_service.start_login("http://127.0.0.1:17493/drive/callback", "test-pc")
    state = url.split("state=")[1].split("&")[0]

    async def fake_post(url, *args, **kwargs):
        assert "oauth2.googleapis.com/token" in url
        return _mock_json_response(
            {
                "refresh_token": "REFRESH",
                "access_token": "ACCESS",
                "expires_in": 3600,
            }
        )

    async def fake_get(url, *args, **kwargs):
        assert "www.googleapis.com/drive/v3/about" in url
        return _mock_json_response({"user": {"emailAddress": "me@example.com"}})

    with patch("httpx.AsyncClient") as mock_client_cls:
        instance = mock_client_cls.return_value
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        instance.post = fake_post
        instance.get = fake_get
        ok, msg = _run_async(drive_service.handle_callback(test_db, code="auth-code", state=state))

    assert ok is True
    status = drive_service.get_status(test_db)
    assert status["connected"] is True
    assert status["account_email"] == "me@example.com"


def test_callback_google_rejects(test_db, mock_creds):
    url = drive_service.start_login("http://127.0.0.1:17493/drive/callback", "test-pc")
    state = url.split("state=")[1].split("&")[0]

    async def fake_post(url, *args, **kwargs):
        return _mock_json_response({"error": "invalid_grant"}, status=400)

    with patch("httpx.AsyncClient") as mock_client_cls:
        instance = mock_client_cls.return_value
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        instance.post = fake_post
        ok, msg = _run_async(drive_service.handle_callback(test_db, code="bad", state=state))

    assert ok is False
    assert "rejected the sign-in code" in msg
    assert drive_service.get_status(test_db)["connected"] is False


def test_run_backup_mirrors_folders(test_db, tmp_path):
    captures = tmp_path / "captures"
    generations = tmp_path / "generations"
    captures.mkdir()
    generations.mkdir()
    (captures / "a.wav").write_bytes(b"1111")
    (captures / "sub").mkdir()
    (captures / "sub" / "b.wav").write_bytes(b"2222")
    (generations / "c.wav").write_bytes(b"3333")

    with patch.object(drive_service.config, "get_captures_dir", return_value=captures), \
         patch.object(drive_service.config, "get_generations_dir", return_value=generations), \
         patch.object(drive_service, "_access_token", return_value=_run_async(drive_service._access_token(test_db))) as tok:
        # seed a connected row with a valid token so _access_token returns it
        drive_service._store_tokens(
            test_db,
            refresh_token="REFRESH",
            access_token="OK",
            expires_in=3600,
            account_email="me@example.com",
        )
        tok.return_value = "OK"

        async def fake_client():
            return None

        calls = {"folders": [], "uploads": []}

        class FakeClient:
            async def get(self, url, params=None, headers=None):
                if url == "https://www.googleapis.com/drive/v3/files":
                    return _mock_json_response({"files": []})
                return _mock_json_response({})

            async def post(self, url, params=None, headers=None, json=None, files=None, **kw):
                if url.startswith("https://www.googleapis.com/drive/v3/files"):
                    calls["folders"].append(json.get("name") if json else params)
                    return _mock_json_response({"id": f"folder-{len(calls['folders'])}", "name": "x"}, status=200)
                calls["uploads"].append(files["metadata"][1])
                return _mock_json_response({"id": "file-id", "name": "x"}, status=200)

        fake_client_obj = FakeClient()
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=fake_client_obj)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = _run_async(drive_service.run_backup(test_db))

    assert result["success"] is True
    assert result["uploaded"] == 3
    assert result["skipped"] == 0
    row = test_db.query(DBDriveSettings).first()
    assert row.root_folder_id is not None
    assert row.last_backup_at is not None


def _run_async(coro):
    import asyncio
    return asyncio.get_event_loop().run_until_complete(coro)
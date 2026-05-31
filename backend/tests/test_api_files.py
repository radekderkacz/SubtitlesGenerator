"""File Browser API tests."""
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.database import get_db
from app.main import app
from app.models.orm import Settings


def _settings(nas_mount_path: str | None) -> Settings:
    now = datetime.now(timezone.utc)
    return Settings(
        id=1,
        nas_mount_path=nas_mount_path,
        transcription_backend=None,
        translation_provider=None,
        translation_model=None,
        translation_api_url=None,
        translation_api_key=None,
        jellyfin_url=None,
        jellyfin_api_key=None,
        hf_token=None,
        created_at=now,
        updated_at=now,
    )


def _override_db_with_settings(row: Settings):
    async def _override():
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=row)
        mock_session.execute = AsyncMock(return_value=mock_result)
        yield mock_session
    return _override


@pytest.mark.asyncio
async def test_browse_returns_422_when_nas_not_configured(client):
    app.dependency_overrides[get_db] = _override_db_with_settings(_settings(None))
    response = await client.get("/api/v1/files/browse")
    assert response.status_code == 422
    assert response.json()["code"] == "NAS_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_browse_root_when_no_path_given(tmp_path, client):
    """No `path` param → list the configured nas_mount_path itself."""
    (tmp_path / "Film.mkv").write_bytes(b"x" * 10)
    (tmp_path / "subdir").mkdir()
    (tmp_path / "ignored.txt").write_text("nope")

    app.dependency_overrides[get_db] = _override_db_with_settings(_settings(str(tmp_path)))
    response = await client.get("/api/v1/files/browse")

    assert response.status_code == 200
    body = response.json()
    assert body["path"] == str(tmp_path)
    assert body["parent"] is None
    assert body["directories"] == ["subdir"]
    assert len(body["files"]) == 1
    assert body["files"][0]["name"] == "Film.mkv"
    assert body["files"][0]["size_bytes"] == 10
    assert body["files"][0]["has_srt"] is False


@pytest.mark.asyncio
async def test_browse_filters_to_video_extensions(tmp_path, client):
    """Only mkv/mp4/avi/m4v/mov are listed; everything else is excluded."""
    for name in ("Film.mkv", "Film.mp4", "Film.avi", "Film.m4v", "Film.mov"):
        (tmp_path / name).write_bytes(b"")
    for name in ("notes.txt", "image.png", "Film.srt", "data.json"):
        (tmp_path / name).write_bytes(b"")

    app.dependency_overrides[get_db] = _override_db_with_settings(_settings(str(tmp_path)))
    response = await client.get("/api/v1/files/browse")

    assert response.status_code == 200
    names = {f["name"] for f in response.json()["files"]}
    assert names == {"Film.mkv", "Film.mp4", "Film.avi", "Film.m4v", "Film.mov"}


@pytest.mark.asyncio
async def test_browse_flags_companion_srt(tmp_path, client):
    """Films with .{lang}.srt or .srt siblings get has_srt=true."""
    (tmp_path / "WithSrt.mkv").write_bytes(b"")
    (tmp_path / "WithSrt.en.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n")
    (tmp_path / "Plain.mkv").write_bytes(b"")
    (tmp_path / "Plain.srt").write_text("")
    (tmp_path / "NoSrt.mkv").write_bytes(b"")

    app.dependency_overrides[get_db] = _override_db_with_settings(_settings(str(tmp_path)))
    response = await client.get("/api/v1/files/browse")

    files = {f["name"]: f["has_srt"] for f in response.json()["files"]}
    assert files == {"WithSrt.mkv": True, "Plain.mkv": True, "NoSrt.mkv": False}


@pytest.mark.asyncio
async def test_browse_subdirectory(tmp_path, client):
    nas = tmp_path
    sub = nas / "movies"
    sub.mkdir()
    (sub / "Film.mkv").write_bytes(b"")

    app.dependency_overrides[get_db] = _override_db_with_settings(_settings(str(nas)))
    response = await client.get(f"/api/v1/files/browse?path={sub}")

    body = response.json()
    assert response.status_code == 200
    assert body["path"] == str(sub)
    assert body["parent"] == str(nas)
    assert {f["name"] for f in body["files"]} == {"Film.mkv"}


@pytest.mark.asyncio
async def test_browse_rejects_path_traversal(tmp_path, client):
    nas = tmp_path / "nas"
    nas.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    app.dependency_overrides[get_db] = _override_db_with_settings(_settings(str(nas)))
    response = await client.get(f"/api/v1/files/browse?path={outside}")

    assert response.status_code == 400
    assert response.json()["code"] == "PATH_TRAVERSAL"


@pytest.mark.asyncio
async def test_browse_returns_404_when_directory_missing(tmp_path, client):
    nas = tmp_path
    missing = nas / "does-not-exist"

    app.dependency_overrides[get_db] = _override_db_with_settings(_settings(str(nas)))
    response = await client.get(f"/api/v1/files/browse?path={missing}")

    assert response.status_code == 404
    assert response.json()["code"] == "DIR_NOT_FOUND"


@pytest.mark.asyncio
async def test_browse_returns_404_when_path_is_a_file(tmp_path, client):
    """A path that exists but isn't a directory should 404."""
    nas = tmp_path
    file_path = nas / "Film.mkv"
    file_path.write_bytes(b"")

    app.dependency_overrides[get_db] = _override_db_with_settings(_settings(str(nas)))
    response = await client.get(f"/api/v1/files/browse?path={file_path}")

    assert response.status_code == 404
    assert response.json()["code"] == "DIR_NOT_FOUND"

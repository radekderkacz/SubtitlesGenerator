from pathlib import Path

import pytest

from app.core.security import ApiError, validate_nas_path, validate_nas_root_allowed


def test_validate_nas_path_allows_valid_path():
    """validate_nas_path returns resolved Path for paths within NAS root."""
    result = validate_nas_path("/media/movies/film.mkv", "/media")
    assert isinstance(result, Path)
    assert str(result).startswith("/media")


def test_validate_nas_path_rejects_traversal():
    """validate_nas_path raises ApiError 400 PATH_TRAVERSAL for paths outside NAS root."""
    try:
        validate_nas_path("/etc/passwd", "/media")
        assert False, "Expected ApiError"
    except ApiError as exc:
        assert exc.status_code == 400
        assert exc.code == "PATH_TRAVERSAL"


@pytest.mark.parametrize(
    "path",
    [
        "/mnt",
        "/mnt/nas",
        "/mnt/nas/movies",
        "/media",
        "/media/library",
        "/srv/media",
        "/data/films",
        "/shared",
        "/shared/movies",
    ],
)
def test_validate_nas_root_allowed_accepts_safe_prefixes(path):
    """validate_nas_root_allowed is a no-op for paths under known mount points."""
    validate_nas_root_allowed(path)


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/etc",
        "/etc/passwd",
        "/root",
        "/home/user/Movies",
        "/var/log",
        "/proc/1/environ",
        "/sys",
        "/usr/share",
        "/tmp",
        "/boot",
        "",
    ],
)
def test_validate_nas_root_allowed_rejects_system_paths(path):
    """validate_nas_root_allowed raises 422 NAS_PATH_NOT_ALLOWED for anything
    not under /mnt, /media, /srv, or /data."""
    with pytest.raises(ApiError) as exc_info:
        validate_nas_root_allowed(path)
    assert exc_info.value.status_code == 422
    assert exc_info.value.code == "NAS_PATH_NOT_ALLOWED"


def test_validate_nas_root_allowed_resolves_traversal():
    """A path that resolves out of an allowed prefix is rejected."""
    with pytest.raises(ApiError) as exc_info:
        validate_nas_root_allowed("/mnt/../etc")
    assert exc_info.value.code == "NAS_PATH_NOT_ALLOWED"

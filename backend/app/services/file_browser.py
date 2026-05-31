"""File browser listing helper. Uses validate_nas_path to enforce that any
caller-supplied path stays under the configured NAS mount root."""
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.media import VIDEO_EXTENSIONS
from app.core.security import ApiError, validate_nas_path


def _has_companion_srt(directory: Path, video_name: str) -> bool:
    """True iff a file named `{stem}.*.srt` (or `{stem}.srt`) exists in `directory`.
    Matches the worker's SRT writer naming convention."""
    stem = Path(video_name).stem
    for entry in directory.iterdir():
        if not entry.is_file():
            continue
        ename = entry.name
        if not ename.endswith(".srt"):
            continue
        # Accept both "Film.srt" and "Film.en.srt" / "Film.fr.srt" / etc.
        if ename == f"{stem}.srt":
            return True
        if ename.startswith(f"{stem}."):
            return True
    return False


def _file_to_dict(entry: Path, has_srt: bool) -> dict[str, Any]:
    stat = entry.stat()
    return {
        "name": entry.name,
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "has_srt": has_srt,
    }


def list_directory(path_arg: str | None, nas_mount_path: str) -> dict[str, Any]:
    """Lists a directory's video files + subdirectories. Returns a dict
    matching ``FileBrowseResponse``.

    Raises ``ApiError(400, PATH_TRAVERSAL)`` if the path escapes the NAS root,
    ``ApiError(404, DIR_NOT_FOUND)`` if the directory doesn't exist.
    """
    target = path_arg if path_arg else nas_mount_path
    resolved = validate_nas_path(target, nas_mount_path)

    if not resolved.exists():
        raise ApiError(404, "DIR_NOT_FOUND", "Directory not found")
    if not resolved.is_dir():
        raise ApiError(404, "DIR_NOT_FOUND", "Path is not a directory")

    directories: list[str] = []
    files: list[dict[str, Any]] = []
    for entry in sorted(resolved.iterdir(), key=lambda p: p.name.lower()):
        if entry.is_dir():
            directories.append(entry.name)
            continue
        if not entry.is_file():
            continue
        if entry.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        files.append(_file_to_dict(entry, _has_companion_srt(resolved, entry.name)))

    nas_root = Path(nas_mount_path).resolve()
    parent = None if resolved == nas_root else str(resolved.parent)

    return {
        "path": str(resolved),
        "parent": parent,
        "directories": directories,
        "files": files,
    }

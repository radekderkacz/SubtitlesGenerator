from pathlib import Path

from fastapi import HTTPException

# Top-level directories the user is allowed to point a NAS root or watch folder
# at. Anything else (`/`, `/etc`, `/root`, `/proc`, …) is refused so a typo or
# misuse can't turn the file browser / worker into a filesystem enumerator.
_ALLOWED_NAS_ROOTS: frozenset[str] = frozenset({"mnt", "media", "srv", "data", "shared"})


class ApiError(HTTPException):
    def __init__(self, status_code: int, code: str, detail: str):
        super().__init__(status_code=status_code, detail=detail)
        self.code = code


def validate_nas_path(path: str, nas_mount_path: str) -> Path:
    if not nas_mount_path:
        raise ApiError(400, "PATH_TRAVERSAL", "Path is outside NAS mount root")
    resolved = Path(path).resolve()
    nas_root = Path(nas_mount_path).resolve()
    if resolved != nas_root and not resolved.is_relative_to(nas_root):
        raise ApiError(400, "PATH_TRAVERSAL", "Path is outside NAS mount root")
    return resolved


def validate_nas_root_allowed(path: str) -> None:
    """Reject NAS roots / watch folders that aren't under one of the
    well-known mount-point parents (``/mnt``, ``/media``, ``/srv``, ``/data``).

    Raises ``ApiError(422, "NAS_PATH_NOT_ALLOWED", …)`` otherwise. The check is
    purely lexical so it works the same whether the path exists or not — the
    "exists / is a directory" check happens separately at the call site.
    """
    resolved = Path(path).resolve()
    parts = resolved.parts
    if len(parts) < 2 or parts[0] != "/" or parts[1] not in _ALLOWED_NAS_ROOTS:
        allowed = ", ".join(f"/{p}" for p in sorted(_ALLOWED_NAS_ROOTS))
        raise ApiError(
            422,
            "NAS_PATH_NOT_ALLOWED",
            f"Path must be under one of: {allowed}",
        )

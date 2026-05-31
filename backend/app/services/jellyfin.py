"""Jellyfin library refresh service

Triggers a Jellyfin library scan after the worker writes an SRT file. The
contract is fire-and-forget: failures are logged at warning level and never
propagate to the caller, so SRT delivery and Jellyfin refresh remain
independent.

Credentials are read from the in-memory Settings model and never written to
the per-job log file.
"""
import logging
from typing import Optional

import httpx

from app.models.orm import Settings

logger = logging.getLogger(__name__)

_REFRESH_PATH = "/Library/Refresh"
_REFRESH_TIMEOUT_S = 10.0


class JellyfinNotConfigured(Exception):
    """Raised when settings have no Jellyfin URL or API key."""


class JellyfinRefreshError(Exception):
    """Raised when Jellyfin returns a non-2xx or the request fails."""


def _credentials(settings: Settings) -> tuple[str, str]:
    url = (settings.jellyfin_url or "").rstrip("/")
    api_key = settings.jellyfin_api_key or ""
    if not url or not api_key:
        raise JellyfinNotConfigured()
    return url, api_key


async def trigger_library_scan(settings: Settings, *, client: Optional[httpx.AsyncClient] = None) -> None:
    """POST `{jellyfin_url}/Library/Refresh` with `X-Emby-Token`.

    Raises:
      JellyfinNotConfigured — when URL or API key is missing.
      JellyfinRefreshError  — on non-2xx response or request error.

    Caller is expected to translate these into the right log treatment;
    `trigger_library_scan_safe` does that automatically and is the right
    entry-point for the worker pipeline.
    """
    if client is not None:
        await _post_refresh(client, settings)
        return
    async with httpx.AsyncClient(timeout=_REFRESH_TIMEOUT_S) as http:
        await _post_refresh(http, settings)


async def _post_refresh(client: httpx.AsyncClient, settings: Settings) -> None:
    url, api_key = _credentials(settings)
    target = f"{url}{_REFRESH_PATH}"
    try:
        response = await client.post(target, headers={"X-Emby-Token": api_key})
        if not (200 <= response.status_code < 300):
            raise JellyfinRefreshError(
                f"Jellyfin returned HTTP {response.status_code}"
            )
    except httpx.HTTPError as e:
        raise JellyfinRefreshError(f"Jellyfin request failed: {e}") from e


async def trigger_library_scan_safe(settings: Settings) -> bool:
    """Wrapper for the worker: returns True on success, False on any failure.

    Never raises. Logs at the appropriate level so the worker's per-job log
    sees the outcome without leaking credentials.
    """
    try:
        await trigger_library_scan(settings)
        logger.info("Jellyfin library refresh triggered")
        return True
    except JellyfinNotConfigured:
        logger.debug("Jellyfin not configured — skipping library refresh")
        return False
    except JellyfinRefreshError as e:
        logger.warning("Jellyfin library refresh failed: %s", e)
        return False

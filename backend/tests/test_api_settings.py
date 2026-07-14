import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx


def _mock_session_with_row(row):
    """Build a mock AsyncSessionLocal context manager that returns `row` from session.get()."""
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=row)
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    mock_factory = MagicMock(return_value=mock_cm)
    return mock_factory, mock_session


# ---------------------------------------------------------------------------
# GET /api/v1/settings
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_settings_happy_path(client, make_settings_row):
    """GET returns 200; credential fields masked; unset fields null; normal fields as-is."""
    row = make_settings_row(
        jellyfin_api_key="real-secret",
        transcription_api_key=None,
    )
    mock_factory, _ = _mock_session_with_row(row)

    with patch("app.api.settings.AsyncSessionLocal", mock_factory):
        response = await client.get("/api/v1/settings")

    assert response.status_code == 200
    data = response.json()
    assert data["jellyfin_api_key"] == "***"
    assert data["transcription_api_key"] is None


@pytest.mark.asyncio
async def test_get_settings_503_when_no_row(client):
    """GET returns 503 when settings row does not exist."""
    mock_factory, _ = _mock_session_with_row(None)

    with patch("app.api.settings.AsyncSessionLocal", mock_factory):
        response = await client.get("/api/v1/settings")

    assert response.status_code == 503


# ---------------------------------------------------------------------------
# PUT /api/v1/settings
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_put_settings_happy_path(client):
    """PUT returns 200 ok and executes upsert with provided fields."""
    mock_factory, mock_session = _mock_session_with_row(None)

    with patch("app.api.settings.AsyncSessionLocal", mock_factory):
        response = await client.put(
            "/api/v1/settings",
            json={"transcription_model": "whisper-1", "nas_mount_path": "/mnt"},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    mock_session.execute.assert_called_once()
    mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_put_settings_invalid_nas_path(client):
    """PUT returns 422 with INVALID_NAS_PATH code when nas_mount_path doesn't exist."""
    response = await client.put(
        "/api/v1/settings",
        json={"nas_mount_path": "/mnt/nonexistent/path/that/does/not/exist"},
    )

    assert response.status_code == 422
    data = response.json()
    assert data["code"] == "INVALID_NAS_PATH"
    # actionable: name the offending path and point at the /media default
    assert "/mnt/nonexistent/path/that/does/not/exist" in data["detail"]
    assert "/media" in data["detail"]


@pytest.mark.asyncio
async def test_put_settings_nas_path_not_allowed(client):
    """PUT rejects nas_mount_path that resolves outside /mnt|/media|/srv|/data
    even if the directory exists."""
    response = await client.put(
        "/api/v1/settings",
        json={"nas_mount_path": "/etc"},
    )

    assert response.status_code == 422
    data = response.json()
    assert data["code"] == "NAS_PATH_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_put_settings_sentinel_skipped(client):
    """PUT with "***" for a credential field skips that field (upsert not called)."""
    mock_factory, mock_session = _mock_session_with_row(None)

    with patch("app.api.settings.AsyncSessionLocal", mock_factory):
        response = await client.put(
            "/api/v1/settings",
            json={"jellyfin_api_key": "***"},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    # update_dict becomes empty → early return, DB never touched
    mock_session.execute.assert_not_called()


# ---------------------------------------------------------------------------
# POST /api/v1/settings/test-jellyfin
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_test_jellyfin_success(client):
    """test-jellyfin returns ok=true and version string when Jellyfin responds 200."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"Version": "10.8.0", "ServerName": "MyJellyfin"}
    mock_response.raise_for_status = MagicMock()

    mock_http_client = AsyncMock()
    mock_http_client.get = AsyncMock(return_value=mock_response)

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("app.api.settings.httpx.AsyncClient", return_value=mock_cm):
        response = await client.post(
            "/api/v1/settings/test-jellyfin",
            json={"url": "http://jellyfin.local", "api_key": "token"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["detail"] == "Connected — Jellyfin 10.8.0"


@pytest.mark.asyncio
async def test_test_jellyfin_failure(client):
    """test-jellyfin returns ok=false when connection is refused."""
    mock_http_client = AsyncMock()
    mock_http_client.get = AsyncMock(
        side_effect=httpx.ConnectError("connection refused")
    )

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("app.api.settings.httpx.AsyncClient", return_value=mock_cm):
        response = await client.post(
            "/api/v1/settings/test-jellyfin",
            json={"url": "http://jellyfin.local", "api_key": "token"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False


# ---------------------------------------------------------------------------
# POST /api/v1/settings/test-transcription
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_test_transcription_remote_success(client):
    """test-transcription returns ok=true for remote-api backend when endpoint responds 200."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"text": "hello world"}
    mock_response.raise_for_status = MagicMock()

    mock_http_client = AsyncMock()
    mock_http_client.post = AsyncMock(return_value=mock_response)

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("app.api.settings.httpx.AsyncClient", return_value=mock_cm):
        response = await client.post(
            "/api/v1/settings/test-transcription",
            json={
                "backend": "remote-api",
                "url": "http://whisper.local",
                "model": "whisper-large-v3",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True


@pytest.mark.asyncio
async def test_test_transcription_remote_failure(client):
    """test-transcription returns ok=false when remote-api connection times out."""
    mock_http_client = AsyncMock()
    mock_http_client.post = AsyncMock(
        side_effect=httpx.ConnectTimeout("timeout")
    )

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("app.api.settings.httpx.AsyncClient", return_value=mock_cm):
        response = await client.post(
            "/api/v1/settings/test-transcription",
            json={
                "backend": "remote-api",
                "url": "http://whisper.local",
                "model": "whisper-large-v3",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False


# ---------------------------------------------------------------------------
# POST /api/v1/settings/test-translation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_test_translation_success(client):
    """test-translation returns ok=true when provider responds 200."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"choices": [{"message": {"content": "hi"}}]}
    mock_response.raise_for_status = MagicMock()

    mock_http_client = AsyncMock()
    mock_http_client.post = AsyncMock(return_value=mock_response)

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("app.api.settings.httpx.AsyncClient", return_value=mock_cm):
        response = await client.post(
            "/api/v1/settings/test-translation",
            json={"provider": "ollama", "url": "http://ollama.local", "model": "llama3"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["detail"] == "Connected"


@pytest.mark.asyncio
async def test_test_translation_failure(client):
    """test-translation returns ok=false when connection is refused."""
    mock_http_client = AsyncMock()
    mock_http_client.post = AsyncMock(
        side_effect=httpx.ConnectError("refused")
    )

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("app.api.settings.httpx.AsyncClient", return_value=mock_cm):
        response = await client.post(
            "/api/v1/settings/test-translation",
            json={"provider": "ollama", "url": "http://ollama.local", "model": "llama3"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False


@pytest.mark.asyncio
async def test_test_translation_uses_correct_google_url(client):
    """User-reported bug 2026-05-15: clicking Test Connection with Google
    as the provider hit ``/v1/chat/completions`` and 404'd. Google's
    OpenAI-compatible shim only exists at ``/v1beta/openai/chat/
    completions`` — the same URL the deeper Test-this-model probe uses.
    Both call sites now share ``_translation_endpoint`` so they can't
    drift apart again."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"choices": [{"message": {"content": "hi"}}]}
    mock_response.raise_for_status = MagicMock()
    mock_http_client = AsyncMock()
    mock_http_client.post = AsyncMock(return_value=mock_response)
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("app.api.settings.httpx.AsyncClient", return_value=mock_cm):
        response = await client.post(
            "/api/v1/settings/test-translation",
            json={
                "provider": "google",
                "model": "gemini-2.0-flash",
                "api_key": "AIza-fake",
            },
        )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    # The exact URL the user's browser saw 404 on — assert we now hit the
    # /v1beta/openai/ shim instead so the regression is caught at test
    # time, not at deploy time.
    posted_url = mock_http_client.post.await_args.args[0]
    assert posted_url == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"


@pytest.mark.asyncio
async def test_test_translation_surfaces_upstream_error_message(client):
    """When the upstream provider returns a 4xx with a JSON body, the
    detail must include the body's ``error.message`` instead of just
    the status code. The previous code surfaced only ``"400 Bad
    Request"`` which gave the user no clue WHY — and the body almost
    always carries the actionable info (model not found, invalid api
    key, quota exceeded, etc)."""
    body = MagicMock()
    body.status_code = 400
    body.reason_phrase = "Bad Request"
    body.json.return_value = {
        "error": {"message": "models/gemma3:27b is not a known Gemini model.", "code": 400}
    }
    err = httpx.HTTPStatusError("Client error '400 Bad Request'", request=MagicMock(), response=body)

    mock_http_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock(side_effect=err)
    mock_http_client.post = AsyncMock(return_value=mock_response)
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("app.api.settings.httpx.AsyncClient", return_value=mock_cm):
        response = await client.post(
            "/api/v1/settings/test-translation",
            json={"provider": "google", "model": "gemma3:27b", "api_key": "AIza-fake"},
        )

    assert response.status_code == 200
    detail = response.json()["detail"]
    # The upstream message reaches the user.
    assert "is not a known Gemini model" in detail
    # And we add the "this looks like an Ollama id" hint for the
    # specific cloud-provider × Ollama-id mismatch that brought us
    # here on 2026-05-15.
    assert "Ollama" in detail or "ollama" in detail


@pytest.mark.asyncio
async def test_test_translation_uses_correct_openrouter_url(client):
    """Companion guard for the Google bug — confirms the same shared
    resolver is what handles OpenRouter too (no parallel branch)."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"choices": [{"message": {"content": "hi"}}]}
    mock_response.raise_for_status = MagicMock()
    mock_http_client = AsyncMock()
    mock_http_client.post = AsyncMock(return_value=mock_response)
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("app.api.settings.httpx.AsyncClient", return_value=mock_cm):
        await client.post(
            "/api/v1/settings/test-translation",
            json={
                "provider": "openrouter",
                "model": "anthropic/claude-3.5-sonnet",
                "api_key": "sk-or-v1-fake",
            },
        )

    posted_url = mock_http_client.post.await_args.args[0]
    assert posted_url == "https://openrouter.ai/api/v1/chat/completions"


# ---------------------------------------------------------------------------
# POST /api/v1/settings/test-translation-model — full probe (2026-05-15)
# ---------------------------------------------------------------------------


def _build_translation_response(content: str):
    """Mock OpenAI-compatible /chat/completions response body."""
    r = MagicMock()
    r.json.return_value = {"choices": [{"message": {"content": content}}]}
    r.raise_for_status = MagicMock()
    return r


def _patch_async_client_responses(responses: list):
    """Mock httpx.AsyncClient so successive ``client.post`` calls return
    successive entries from ``responses`` (each either a response Mock or
    an Exception to raise)."""
    call_index = {"i": 0}

    async def _post(*args, **kwargs):
        i = call_index["i"]
        call_index["i"] += 1
        r = responses[i]
        if isinstance(r, Exception):
            raise r
        return r

    mock_http_client = AsyncMock()
    mock_http_client.post = AsyncMock(side_effect=_post)
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_cm.__aexit__ = AsyncMock(return_value=None)
    return mock_cm


@pytest.mark.asyncio
async def test_test_translation_model_happy_path(client):
    """Recommended-tier model: preserves 'Spider' in the translation AND
    returns a valid JSON array glossary. End-to-end success."""
    translation = _build_translation_response(
        "Powiedz mi jeszcze jedną rzecz. ... kazałem wrócić po Spidera."
    )
    glossary = _build_translation_response(
        '["Spider", "Jake", "Neytiri", "Pandora", "Na\'vi", "RDA", "unobtainium", '
        '"AMP suit", "Hell\'s Gate", "Lo\'ak", "Kiri", "Tuk", "Quaritch"]'
    )
    cm = _patch_async_client_responses([translation, glossary])
    with patch("app.api.settings.httpx.AsyncClient", return_value=cm):
        response = await client.post(
            "/api/v1/settings/test-translation-model",
            json={
                "provider": "ollama",
                "url": "http://ollama.local:11434",
                "model": "gemma3:27b",
                "target_language": "pl",
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["preserves_proper_nouns"] is True
    assert body["glossary_json_valid"] is True
    assert body["sec_per_segment"] is not None
    # Spider appears (in some Polish-declension form) in the sample.
    assert "spider" in body["sample_translation"].lower()
    # At least 3 terms; the recommended-tier mock returned 13.
    assert len(body["sample_glossary"]) >= 3
    # User-facing detail names all three signals so the result card has
    # enough to render without further translation.
    assert "preserved" in body["detail"].lower()
    assert "valid json" in body["detail"].lower()


@pytest.mark.asyncio
async def test_test_translation_model_translates_spider_to_animal_word_fails_proper_noun_check(client):
    """If the model translates the *name* Spider to the Polish *word*
    pająk, our lowercase substring check for 'spider' misses — that's
    the exact gpt-oss/aya failure mode from 2026-05-15 and the whole
    reason this probe exists."""
    translation = _build_translation_response(
        "Powiedz mi jeszcze jedną rzecz... kazałem wrócić po pająka."  # "spider" as a word
    )
    glossary = _build_translation_response('["Jake", "Neytiri", "Pandora"]')
    cm = _patch_async_client_responses([translation, glossary])
    with patch("app.api.settings.httpx.AsyncClient", return_value=cm):
        response = await client.post(
            "/api/v1/settings/test-translation-model",
            json={"provider": "ollama", "url": "http://x", "model": "bad-model"},
        )
    body = response.json()
    assert body["ok"] is False
    assert body["preserves_proper_nouns"] is False
    # Glossary still works in this scenario (some models fail one check
    # but not the other); ok=False because both must pass.
    assert body["glossary_json_valid"] is True


@pytest.mark.asyncio
async def test_test_translation_model_aya_long_context_format_collapse(client):
    """The aya-expanse failure mode: translation works (preserves Spider)
    but the glossary call returns prose instead of JSON, so the parser
    returns no array. This must surface as glossary_json_valid=false +
    overall ok=false."""
    translation = _build_translation_response(
        "Powiedz mi jeszcze jedną rzecz... wrócić po Spidera."
    )
    # Aya's actual long-context output style: narrative analysis, no JSON.
    glossary = _build_translation_response(
        "It appears that you've provided a list of phrases. "
        "Characters: Neytiri, Jake, Lo'ak, Kiri, Spider, Quaritch."
    )
    cm = _patch_async_client_responses([translation, glossary])
    with patch("app.api.settings.httpx.AsyncClient", return_value=cm):
        response = await client.post(
            "/api/v1/settings/test-translation-model",
            json={"provider": "ollama", "url": "http://x", "model": "aya-expanse:32b"},
        )
    body = response.json()
    assert body["preserves_proper_nouns"] is True
    assert body["glossary_json_valid"] is False
    assert body["sample_glossary"] is None
    assert body["ok"] is False


@pytest.mark.asyncio
async def test_test_translation_model_network_error_returns_failure(client):
    """If the translation probe itself can't even reach the provider, we
    return ok=false + a diagnostic detail; the glossary probe is skipped
    entirely. Don't propagate raw exception strings (might contain
    API keys in the URL)."""
    cm = _patch_async_client_responses([httpx.ConnectError("connection refused")])
    with patch("app.api.settings.httpx.AsyncClient", return_value=cm):
        response = await client.post(
            "/api/v1/settings/test-translation-model",
            json={"provider": "ollama", "url": "http://broken", "model": "x"},
        )
    body = response.json()
    assert body["ok"] is False
    assert body["preserves_proper_nouns"] is None
    assert body["glossary_json_valid"] is None
    assert body["sample_translation"] is None
    assert "Translation probe failed" in body["detail"]


@pytest.mark.asyncio
async def test_test_translation_model_glossary_only_fails_translation_works(client):
    """If only the glossary fetch errors (translation succeeded), we
    still report the partial result instead of treating it as a hard
    failure. The user can decide whether to trust the model without
    the glossary safety net."""
    translation = _build_translation_response(
        "Powiedz mi... wrócić po Spidera."
    )
    cm = _patch_async_client_responses(
        [translation, httpx.ReadTimeout("timed out after 120s")]
    )
    with patch("app.api.settings.httpx.AsyncClient", return_value=cm):
        response = await client.post(
            "/api/v1/settings/test-translation-model",
            json={"provider": "ollama", "url": "http://ok", "model": "x"},
        )
    body = response.json()
    assert body["preserves_proper_nouns"] is True
    assert body["glossary_json_valid"] is False
    assert body["sample_translation"] is not None  # translation result preserved
    assert body["ok"] is False  # ok requires BOTH checks


@pytest.mark.asyncio
async def test_test_translation_model_routes_openrouter_to_correct_endpoint(client):
    """OpenRouter is a fan-out gateway with a fixed cloud endpoint
    (`openrouter.ai/api/v1/chat/completions`). The probe must hit that
    URL — not OpenAI's or Ollama's — when ``provider='openrouter'``.
    Caught a real bug class: the probe formerly fell into the
    "ollama + future OpenAI-compatible" branch which would have built
    a nonsense empty-base URL."""
    translation = _build_translation_response("Powiedz... po Spidera.")
    glossary = _build_translation_response('["Spider", "Jake", "Neytiri"]')
    cm = _patch_async_client_responses([translation, glossary])
    with patch("app.api.settings.httpx.AsyncClient", return_value=cm):
        response = await client.post(
            "/api/v1/settings/test-translation-model",
            json={
                "provider": "openrouter",
                "model": "anthropic/claude-3.5-sonnet",
                "api_key": "sk-or-v1-fake",
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    # Confirm the actual upstream URL used.
    posted_url = cm.__aenter__.return_value.post.await_args_list[0].args[0]
    assert posted_url == "https://openrouter.ai/api/v1/chat/completions"
    # Bearer header should carry the OpenRouter key.
    posted_headers = cm.__aenter__.return_value.post.await_args_list[0].kwargs["headers"]
    assert posted_headers.get("Authorization") == "Bearer sk-or-v1-fake"


# ---------------------------------------------------------------------------
# POST /api/v1/settings/list-translation-models
# ---------------------------------------------------------------------------


def _mock_models_response(model_ids):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": [{"id": mid, "object": "model"} for mid in model_ids],
    }
    mock_response.raise_for_status = MagicMock()
    mock_http_client = AsyncMock()
    mock_http_client.get = AsyncMock(return_value=mock_response)
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_cm.__aexit__ = AsyncMock(return_value=None)
    return mock_cm, mock_http_client


@pytest.mark.asyncio
async def test_list_translation_models_ollama(client):
    """list-translation-models returns sorted unique IDs from /v1/models."""
    mock_cm, http = _mock_models_response(
        ["qwen3.5:9b", "llama3:8b", "qwen3.5:9b"]  # duplicate to verify dedupe
    )

    with patch("app.api.settings.httpx.AsyncClient", return_value=mock_cm):
        response = await client.post(
            "/api/v1/settings/list-translation-models",
            json={"provider": "ollama", "url": "http://ollama.local:11434"},
        )

    assert response.status_code == 200
    assert response.json() == {"models": ["llama3:8b", "qwen3.5:9b"], "detail": None}
    http.get.assert_called_once()
    called_url, _ = http.get.call_args
    assert called_url[0] == "http://ollama.local:11434/v1/models"


@pytest.mark.asyncio
async def test_list_translation_models_ollama_strips_trailing_v1(client):
    """A URL that already ends in /v1 is collapsed — we don't end up at /v1/v1/models."""
    mock_cm, http = _mock_models_response(["llama3:8b"])

    with patch("app.api.settings.httpx.AsyncClient", return_value=mock_cm):
        await client.post(
            "/api/v1/settings/list-translation-models",
            json={"provider": "ollama", "url": "http://ollama.local:11434/v1"},
        )

    called_url, _ = http.get.call_args
    assert called_url[0] == "http://ollama.local:11434/v1/models"


@pytest.mark.asyncio
async def test_list_translation_models_openai_uses_fixed_endpoint(client):
    """For OpenAI the URL is ignored; api.openai.com/v1/models is used."""
    mock_cm, http = _mock_models_response(["gpt-4o", "gpt-3.5-turbo"])

    with patch("app.api.settings.httpx.AsyncClient", return_value=mock_cm):
        await client.post(
            "/api/v1/settings/list-translation-models",
            json={"provider": "openai", "api_key": "sk-test"},
        )

    called_url, kwargs = http.get.call_args
    assert called_url[0] == "https://api.openai.com/v1/models"
    assert kwargs["headers"]["Authorization"] == "Bearer sk-test"


@pytest.mark.asyncio
async def test_list_translation_models_google_uses_fixed_endpoint(client):
    """Google's OpenAI-compat shim DOES expose /v1beta/openai/models —
    the previous test that assumed otherwise was wrong. The endpoint
    requires a valid Bearer token (Google rejects the call as 400 INVALID
    _ARGUMENT without one), and returns the standard OpenAI-shaped
    {data: [{id: ...}]} payload."""
    mock_cm, http = _mock_models_response(
        ["models/gemini-2.0-flash", "models/gemini-1.5-pro", "models/gemini-1.5-flash"]
    )
    with patch("app.api.settings.httpx.AsyncClient", return_value=mock_cm):
        response = await client.post(
            "/api/v1/settings/list-translation-models",
            json={"provider": "google", "api_key": "AIza-test"},
        )
    assert response.status_code == 200
    data = response.json()
    # Sorted ids — exactly what the parser produces.
    assert "models/gemini-1.5-flash" in data["models"]
    assert "models/gemini-2.0-flash" in data["models"]
    called_url, kwargs = http.get.call_args
    assert called_url[0] == "https://generativelanguage.googleapis.com/v1beta/openai/models"
    assert kwargs["headers"]["Authorization"] == "Bearer AIza-test"


@pytest.mark.asyncio
async def test_list_translation_models_unknown_provider(client):
    """A truly unknown provider returns empty list with explanatory detail."""
    response = await client.post(
        "/api/v1/settings/list-translation-models",
        json={"provider": "does-not-exist", "api_key": "x"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["models"] == []
    assert "does-not-exist" in (data.get("detail") or "")


@pytest.mark.asyncio
async def test_list_translation_models_network_error(client):
    """Connection errors return empty list + detail (UI falls back to text input)."""
    mock_http_client = AsyncMock()
    mock_http_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("app.api.settings.httpx.AsyncClient", return_value=mock_cm):
        response = await client.post(
            "/api/v1/settings/list-translation-models",
            json={"provider": "ollama", "url": "http://nope:11434"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["models"] == []
    assert data["detail"]


@pytest.mark.asyncio
async def test_list_translation_models_masked_key_resolves_from_db(client, make_settings_row):
    """An ``***`` api_key (the UI-masked sentinel) must un-mask the stored
    OpenAI key from the DB and forward it as Bearer auth — NOT be dropped,
    which left the request unauthenticated and produced the 400 the user
    reported (2026-05-16). Companion to the Google case so the OpenAI
    provider is covered too."""
    row = make_settings_row(translation_provider="openai", translation_api_key="sk-stored")
    mock_factory, _ = _mock_session_with_row(row)
    mock_cm, http = _mock_models_response(["gpt-4o"])

    with patch("app.api.settings.AsyncSessionLocal", mock_factory), \
         patch("app.api.settings.httpx.AsyncClient", return_value=mock_cm):
        await client.post(
            "/api/v1/settings/list-translation-models",
            json={"provider": "openai", "api_key": "***"},
        )

    _, kwargs = http.get.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer sk-stored"


@pytest.mark.asyncio
async def test_test_jellyfin_uses_stored_key_when_sentinel(client, make_settings_row):
    """test-jellyfin with api_key="***" uses the stored jellyfin_api_key from DB."""
    row = make_settings_row(jellyfin_api_key="real-secret")
    mock_factory, _ = _mock_session_with_row(row)

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"Version": "10.9.3"})

    mock_http_client = AsyncMock()
    mock_http_client.get = AsyncMock(return_value=mock_response)

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("app.api.settings.AsyncSessionLocal", mock_factory), \
         patch("app.api.settings.httpx.AsyncClient", return_value=mock_cm):
        response = await client.post(
            "/api/v1/settings/test-jellyfin",
            json={"url": "http://jf.local", "api_key": "***"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    mock_http_client.get.assert_called_once()
    _, call_kwargs = mock_http_client.get.call_args
    assert call_kwargs["headers"]["X-Emby-Token"] == "real-secret"


@pytest.mark.asyncio
async def test_test_jellyfin_returns_not_configured_when_no_stored_key(client, make_settings_row):
    """test-jellyfin with api_key="***" and no stored key returns ok=False without calling httpx."""
    row = make_settings_row(jellyfin_api_key=None)
    mock_factory, _ = _mock_session_with_row(row)

    with patch("app.api.settings.AsyncSessionLocal", mock_factory), \
         patch("app.api.settings.httpx.AsyncClient") as mock_http_client_cls:
        response = await client.post(
            "/api/v1/settings/test-jellyfin",
            json={"url": "http://jf.local", "api_key": "***"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert data["detail"] == "API key not configured"
    mock_http_client_cls.assert_not_called()


# ---------------------------------------------------------------------------
# Masked-credential resolution (2026-05-16 bug class)
#
# Stored provider keys are masked as "***" to the browser, and the frontend
# omits the sentinel on Test/Refresh. Every provider test/refresh path must
# therefore un-mask the real key from the DB — exactly like test-jellyfin
# already does (settings.py:207-213). Before the fix these requests went out
# with NO Authorization header and Google returned 400 ("Missing or invalid
# Authorization header."), the user-reported symptom. The PUT writer keeps
# its opposite (strip-"***") semantics — covered separately above.
# ---------------------------------------------------------------------------


def _mock_post_client(json_body=None):
    mock_response = MagicMock()
    mock_response.json.return_value = json_body or {
        "choices": [{"message": {"content": "hi"}}]
    }
    mock_response.raise_for_status = MagicMock()
    mock_http_client = AsyncMock()
    mock_http_client.post = AsyncMock(return_value=mock_response)
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_cm.__aexit__ = AsyncMock(return_value=None)
    return mock_cm, mock_http_client


@pytest.mark.asyncio
async def test_test_translation_resolves_masked_key_from_db(client, make_settings_row):
    """The exact user bug: Google + Test Connection with the stored key
    masked as "***" must un-mask the real key from the DB and send it as
    Bearer auth (not no auth → 400)."""
    row = make_settings_row(translation_provider="google", translation_api_key="stored-google-key")
    mock_factory, _ = _mock_session_with_row(row)
    mock_cm, http = _mock_post_client()

    with patch("app.api.settings.AsyncSessionLocal", mock_factory), \
         patch("app.api.settings.httpx.AsyncClient", return_value=mock_cm):
        response = await client.post(
            "/api/v1/settings/test-translation",
            json={"provider": "google", "model": "gemini-2.0-flash", "api_key": "***"},
        )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    _, kwargs = http.post.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer stored-google-key"


@pytest.mark.asyncio
async def test_test_translation_freshly_typed_key_wins_over_db(client, make_settings_row):
    """Test-before-save must still work: a real key in the request beats
    whatever is stored."""
    row = make_settings_row(translation_provider="google", translation_api_key="old-stored")
    mock_factory, _ = _mock_session_with_row(row)
    mock_cm, http = _mock_post_client()

    with patch("app.api.settings.AsyncSessionLocal", mock_factory), \
         patch("app.api.settings.httpx.AsyncClient", return_value=mock_cm):
        await client.post(
            "/api/v1/settings/test-translation",
            json={"provider": "google", "model": "gemini-2.0-flash", "api_key": "fresh-typed"},
        )

    _, kwargs = http.post.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer fresh-typed"


@pytest.mark.asyncio
async def test_test_translation_not_configured_when_no_key_anywhere(client, make_settings_row):
    """Cloud provider + no key typed + nothing stored → friendly message,
    no doomed upstream call (mirrors test-jellyfin line 212)."""
    row = make_settings_row(translation_provider="google", translation_api_key=None)
    mock_factory, _ = _mock_session_with_row(row)

    with patch("app.api.settings.AsyncSessionLocal", mock_factory), \
         patch("app.api.settings.httpx.AsyncClient") as http_cls:
        response = await client.post(
            "/api/v1/settings/test-translation",
            json={"provider": "google", "model": "gemini-2.0-flash", "api_key": "***"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert data["detail"] == "API key not configured"
    http_cls.assert_not_called()


@pytest.mark.asyncio
async def test_list_translation_models_resolves_masked_key_from_db(client, make_settings_row):
    """The exact 'Refresh models → 400' bug: list-translation-models must
    un-mask the stored key so Google's /v1beta/openai/models gets Bearer
    auth instead of 'Missing or invalid Authorization header.'"""
    row = make_settings_row(translation_provider="google", translation_api_key="stored-google-key")
    mock_factory, _ = _mock_session_with_row(row)
    mock_cm, http = _mock_models_response(["gemini-2.0-flash", "gemini-1.5-pro"])

    with patch("app.api.settings.AsyncSessionLocal", mock_factory), \
         patch("app.api.settings.httpx.AsyncClient", return_value=mock_cm):
        response = await client.post(
            "/api/v1/settings/list-translation-models",
            json={"provider": "google", "api_key": "***"},
        )

    assert response.status_code == 200
    assert response.json()["models"] == ["gemini-1.5-pro", "gemini-2.0-flash"]
    _, kwargs = http.get.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer stored-google-key"


@pytest.mark.asyncio
async def test_list_translation_models_not_configured_when_no_key(client, make_settings_row):
    """Cloud provider, no key anywhere → models=[] with the same friendly
    detail instead of a raw upstream 400."""
    row = make_settings_row(translation_provider="google", translation_api_key=None)
    mock_factory, _ = _mock_session_with_row(row)

    with patch("app.api.settings.AsyncSessionLocal", mock_factory), \
         patch("app.api.settings.httpx.AsyncClient") as http_cls:
        response = await client.post(
            "/api/v1/settings/list-translation-models",
            json={"provider": "google"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["models"] == []
    assert data["detail"] == "API key not configured"
    http_cls.assert_not_called()


@pytest.mark.asyncio
async def test_test_translation_model_resolves_masked_key_from_db(client, make_settings_row):
    """The deeper 'Test this model' probe shares the same gap."""
    row = make_settings_row(translation_provider="google", translation_api_key="stored-google-key")
    mock_factory, _ = _mock_session_with_row(row)
    mock_cm, http = _mock_post_client(
        {"choices": [{"message": {"content": "Spider-Man rescued the cat."}}]}
    )

    with patch("app.api.settings.AsyncSessionLocal", mock_factory), \
         patch("app.api.settings.httpx.AsyncClient", return_value=mock_cm):
        response = await client.post(
            "/api/v1/settings/test-translation-model",
            json={
                "provider": "google",
                "model": "gemini-2.0-flash",
                "target_language": "Polish",
                "api_key": "***",
            },
        )

    assert response.status_code == 200
    _, kwargs = http.post.call_args_list[0]
    assert kwargs["headers"]["Authorization"] == "Bearer stored-google-key"


@pytest.mark.asyncio
async def test_test_transcription_remote_resolves_masked_key_from_db(client, make_settings_row):
    """Remote transcription API shares the identical masked-key gap."""
    row = make_settings_row(transcription_api_key="stored-whisper-key")
    mock_factory, _ = _mock_session_with_row(row)
    mock_cm, http = _mock_post_client({"text": "hello"})

    with patch("app.api.settings.AsyncSessionLocal", mock_factory), \
         patch("app.api.settings.httpx.AsyncClient", return_value=mock_cm):
        response = await client.post(
            "/api/v1/settings/test-transcription",
            json={
                "backend": "remote-api",
                "url": "https://api.openai.com",
                "model": "whisper-1",
                "api_key": "***",
            },
        )

    assert response.status_code == 200
    _, kwargs = http.post.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer stored-whisper-key"


# ---------------------------------------------------------------------------
# WS5 (2026-07 audit): per-profile credential masking round-trip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_settings_masks_profile_api_keys(client, make_settings_row):
    """Profile API keys must never reach the browser raw."""
    row = make_settings_row(profiles=[{
        "name": "P1",
        "transcription_api_key": "raw-trans-key",
        "translation_api_key": "raw-transl-key",
        "translation_provider": "openai",
    }])
    mock_factory, _ = _mock_session_with_row(row)
    with patch("app.api.settings.AsyncSessionLocal", mock_factory):
        response = await client.get("/api/v1/settings")
    assert response.status_code == 200
    profile = response.json()["profiles"][0]
    assert profile["transcription_api_key"] == "***"
    assert profile["translation_api_key"] == "***"
    assert profile["translation_provider"] == "openai"


@pytest.mark.asyncio
async def test_put_settings_resolves_masked_profile_keys(client, make_settings_row):
    """A client round-tripping masked profiles must not store literal '***'
    (which the worker would send as Authorization: Bearer *** — the exact
    recurring-Google-400 class already fixed for top-level keys)."""
    stored = make_settings_row(profiles=[{
        "name": "P1",
        "transcription_api_key": "stored-trans-key",
        "translation_api_key": "stored-transl-key",
    }])
    mock_factory, mock_session = _mock_session_with_row(stored)
    with patch("app.api.settings.AsyncSessionLocal", mock_factory):
        response = await client.put("/api/v1/settings", json={"profiles": [{
            "name": "P1",
            "transcription_api_key": "***",
            "translation_api_key": "new-key",
        }]})
    assert response.status_code == 200
    stmt = mock_session.execute.await_args.args[0]
    values = stmt.compile().params
    import json as _json
    profiles = values["profiles"]
    if isinstance(profiles, str):
        profiles = _json.loads(profiles)
    assert profiles[0]["transcription_api_key"] == "stored-trans-key"  # unmasked
    assert profiles[0]["translation_api_key"] == "new-key"             # replaced

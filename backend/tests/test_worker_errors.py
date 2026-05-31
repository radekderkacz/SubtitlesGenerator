import httpx, pytest, time
from app.worker.errors import TransientPipelineError, is_transient, retry_call

def _httpx_status(code):
    req = httpx.Request("POST", "http://x/")
    resp = httpx.Response(code, request=req)
    return httpx.HTTPStatusError(f"{code}", request=req, response=resp)

@pytest.mark.parametrize("code", [500, 502, 503, 504, 408, 429])
def test_5xx_429_408_transient(code):
    assert is_transient(_httpx_status(code)) is True

@pytest.mark.parametrize("code", [400, 401, 403, 404, 413, 422])
def test_4xx_terminal(code):
    assert is_transient(_httpx_status(code)) is False

def test_timeout_connect_transient():
    assert is_transient(httpx.ConnectTimeout("t")) is True
    assert is_transient(httpx.ReadTimeout("t")) is True
    assert is_transient(httpx.ConnectError("c")) is True

def test_logic_errors_terminal():
    assert is_transient(ValueError("x")) is False
    assert is_transient(RuntimeError("Remote transcription failed: 400 Bad Request")) is False

def test_transient_pipeline_error_is_transient():
    assert is_transient(TransientPipelineError("remote-transcription", ValueError("x"))) is True

def test_retry_call_success_first_try():
    assert retry_call(lambda: 7, step="s", backoffs=[0, 0]) == 7

def test_retry_call_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    calls = {"n": 0}
    def f():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _httpx_status(503)
        return "ok"
    assert retry_call(f, step="s", backoffs=[0, 0, 0]) == "ok"
    assert calls["n"] == 3

def test_retry_call_terminal_reraises_immediately():
    calls = {"n": 0}
    def f():
        calls["n"] += 1
        raise _httpx_status(400)
    with pytest.raises(httpx.HTTPStatusError):
        retry_call(f, step="s", backoffs=[0, 0, 0])
    assert calls["n"] == 1  # no retry on terminal

def test_retry_call_exhausted_transient_raises_TPE(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    def f():
        raise _httpx_status(500)
    with pytest.raises(TransientPipelineError) as ei:
        retry_call(f, step="remote-transcription", backoffs=[0, 0])
    assert ei.value.step == "remote-transcription"
    assert isinstance(ei.value.cause, httpx.HTTPStatusError)

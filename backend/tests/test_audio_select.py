"""Audio-stream selection for extraction (WS7, 2026-07 audit): ffmpeg's
default picks the stream with the MOST channels — a 5.1 commentary or
foreign dub beats the stereo original and the whole SRT comes out wrong."""
from app.worker.audio import audio_filter_for, pick_audio_stream


def _stream(idx, lang=None, channels=2, default=False, layout=None, codec="audio"):
    s = {"index": idx, "codec_type": codec, "channels": channels,
         "disposition": {"default": 1 if default else 0}}
    if lang:
        s["tags"] = {"language": lang}
    if layout:
        s["channel_layout"] = layout
    return s


def test_language_hint_wins_over_default_disposition():
    probe = {"streams": [
        _stream(0, codec="video"),
        _stream(1, lang="fre", channels=6, default=True),   # French dub, 5.1
        _stream(2, lang="eng", channels=2),                  # original stereo
    ]}
    picked, rel = pick_audio_stream(probe, "en")
    assert picked["tags"]["language"] == "eng"
    assert rel == 1  # second AUDIO stream


def test_default_disposition_beats_first():
    probe = {"streams": [
        _stream(0, lang="eng", channels=6),        # commentary 5.1, first
        _stream(1, lang="eng", channels=2, default=True),
    ]}
    picked, rel = pick_audio_stream(probe, None)
    assert rel == 1


def test_falls_back_to_first_audio_stream():
    probe = {"streams": [_stream(0, codec="video"), _stream(1), _stream(2)]}
    picked, rel = pick_audio_stream(probe, "pl")  # no polish track
    assert rel == 0


def test_no_audio_returns_none():
    probe = {"streams": [_stream(0, codec="video")]}
    assert pick_audio_stream(probe, None) == (None, None)


def test_three_letter_hint_matches():
    probe = {"streams": [_stream(0, lang="pol"), _stream(1, lang="eng")]}
    _, rel = pick_audio_stream(probe, "pl")
    assert rel == 0


def test_center_channel_filter_only_when_opted_in(monkeypatch):
    surround = _stream(0, channels=6, layout="5.1(side)")
    stereo = _stream(1, channels=2)
    monkeypatch.delenv("SUBGEN_CENTER_CHANNEL", raising=False)
    assert audio_filter_for(surround) is None            # default: full downmix
    monkeypatch.setenv("SUBGEN_CENTER_CHANNEL", "1")
    assert audio_filter_for(surround) == "pan=mono|c0=FC"
    assert audio_filter_for(stereo) is None              # stereo never pans


# ---------------------------------------------------------------------------
# Speech normalization (faint-dialogue rescue) — extraction filter chain
# ---------------------------------------------------------------------------

def test_speech_norm_on_by_default(monkeypatch):
    monkeypatch.delenv("SUBGEN_DISABLE_SPEECHNORM", raising=False)
    from app.worker.audio import speech_norm_filter
    assert speech_norm_filter() == "speechnorm=e=12.5:r=0.0001:l=1"


def test_speech_norm_opt_out(monkeypatch):
    monkeypatch.setenv("SUBGEN_DISABLE_SPEECHNORM", "1")
    from app.worker.audio import speech_norm_filter
    assert speech_norm_filter() is None


def test_extraction_filters_norm_only_for_stereo(monkeypatch):
    monkeypatch.delenv("SUBGEN_DISABLE_SPEECHNORM", raising=False)
    monkeypatch.delenv("SUBGEN_CENTER_CHANNEL", raising=False)
    from app.worker.audio import extraction_filters
    stereo = {"channels": 2, "channel_layout": "stereo"}
    assert extraction_filters(stereo) == "speechnorm=e=12.5:r=0.0001:l=1"


def test_extraction_filters_pan_then_norm(monkeypatch):
    monkeypatch.setenv("SUBGEN_CENTER_CHANNEL", "1")
    monkeypatch.delenv("SUBGEN_DISABLE_SPEECHNORM", raising=False)
    from app.worker.audio import extraction_filters
    surround = {"channels": 6, "channel_layout": "5.1"}
    # Pan must run first so normalization applies to the isolated dialogue channel.
    assert extraction_filters(surround) == "pan=mono|c0=FC,speechnorm=e=12.5:r=0.0001:l=1"


def test_extraction_filters_none_when_all_disabled(monkeypatch):
    monkeypatch.setenv("SUBGEN_DISABLE_SPEECHNORM", "1")
    monkeypatch.delenv("SUBGEN_CENTER_CHANNEL", raising=False)
    from app.worker.audio import extraction_filters
    assert extraction_filters({"channels": 2, "channel_layout": "stereo"}) is None

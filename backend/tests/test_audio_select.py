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

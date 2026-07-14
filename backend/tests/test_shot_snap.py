"""Shot-change cue snapping (WS14, 2026-07 audit)."""
from app.worker.shot_snap import parse_showinfo_times, snap_cues_to_shots


def _cue(start, end):
    return {"start": start, "end": end, "text": "x"}


def test_parse_showinfo_times():
    err = ("[Parsed_showinfo_1 @ 0x1] n:0 pts:250 pts_time:10.417 duration:1\n"
           "[Parsed_showinfo_1 @ 0x1] n:1 pts:900 pts_time:37.5 fmt:yuv420p\n")
    assert parse_showinfo_times(err) == [10.417, 37.5]


def test_end_just_before_cut_extends_to_guard():
    out = snap_cues_to_shots([_cue(5.0, 9.7)], cuts=[10.0])
    assert abs(out[0]["end"] - (10.0 - 2 / 24)) < 1e-6


def test_end_just_after_cut_retracts_before_it():
    out = snap_cues_to_shots([_cue(5.0, 10.2)], cuts=[10.0])
    assert out[0]["end"] < 10.0


def test_start_near_cut_snaps_onto_it():
    out = snap_cues_to_shots([_cue(10.2, 14.0)], cuts=[10.0])
    assert out[0]["start"] == 10.0


def test_far_boundaries_untouched():
    out = snap_cues_to_shots([_cue(3.0, 6.0)], cuts=[10.0])
    assert out[0] == _cue(3.0, 6.0)


def test_snap_never_crushes_cue():
    # snapping both boundaries toward the same cut would invert the cue
    out = snap_cues_to_shots([_cue(9.8, 10.2)], cuts=[10.0])
    assert out[0]["end"] - out[0]["start"] >= 0.4 - 1e-9  # reverted


def test_no_cuts_is_noop():
    cues = [_cue(1.0, 2.0)]
    assert snap_cues_to_shots(cues, cuts=[]) == cues

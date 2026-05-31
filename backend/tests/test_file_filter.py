from app.services.trigger_executor import file_filter_matches

def _trig(file_filter, type_="watch", config=None):
    return type("T", (), {"type": type_, "config": config or {"path": "/shared/TV"},
                          "file_filter": file_filter})()

def test_all_always_matches():
    assert file_filter_matches(_trig({"type": "all", "value": None}), "/shared/TV/x.mkv")

def test_none_filter_defaults_to_all():
    assert file_filter_matches(_trig(None), "/shared/TV/x.mkv")

def test_subfolder_matches_relative_prefix():
    t = _trig({"type": "subfolder", "value": "Marshals"})
    assert file_filter_matches(t, "/shared/TV/Marshals/S01E01.mkv")
    assert not file_filter_matches(t, "/shared/TV/Avatar/movie.mkv")

def test_name_contains_case_insensitive():
    t = _trig({"type": "name_contains", "value": "marshals"})
    assert file_filter_matches(t, "/shared/TV/X/Marshals - S01E01.mkv")
    assert not file_filter_matches(t, "/shared/TV/X/Avatar.mkv")

import pytest
from pydantic import ValidationError
from app.models.schemas import JobCreate


def test_jobcreate_defaults_source_auto_no_translate():
    j = JobCreate(file_path="/m/x.mkv", profile_name="p1")
    assert j.source_language == "auto"
    assert j.translate is False
    assert j.target_language is None


def test_jobcreate_translate_requires_concrete_target():
    with pytest.raises(ValidationError, match="target language"):
        JobCreate(file_path="/m/x.mkv", profile_name="p1", translate=True)
    with pytest.raises(ValidationError, match="target language"):
        JobCreate(file_path="/m/x.mkv", profile_name="p1", translate=True, target_language="auto")


def test_jobcreate_translate_with_target_ok():
    j = JobCreate(file_path="/m/x.mkv", profile_name="p1", translate=True, target_language="pl")
    assert j.target_language == "pl"


def test_jobcreate_profile_name_required():
    with pytest.raises(ValidationError):
        JobCreate(file_path="/m/x.mkv")

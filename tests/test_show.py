import pytest

from visualgen.instruction import TransitionMode
from visualgen.show import Show, ShowError, load_show


def write_show(tmp_path, text):
    p = tmp_path / "show.yaml"
    p.write_text(text)
    return p


def make_video(tmp_path, name):
    v = tmp_path / name
    v.write_bytes(b"\x00")  # existence is all load_show checks
    return v


def test_loads_valid_show(tmp_path):
    make_video(tmp_path, "a.mp4")
    make_video(tmp_path, "b.mp4")
    p = write_show(tmp_path, "show:\n  - {id: intro, source: a.mp4}\n  - {id: verse, source: b.mp4}\n")
    show = load_show(p)
    assert isinstance(show, Show)
    assert [c.id for c in show.cues] == ["intro", "verse"]
    assert show.cues[0].source == (tmp_path / "a.mp4").resolve()
    assert show.wrap is False


def test_wrap_flag(tmp_path):
    make_video(tmp_path, "a.mp4")
    p = write_show(tmp_path, "wrap: true\nshow:\n  - {id: a, source: a.mp4}\n")
    assert load_show(p).wrap is True


def test_transition_defaults_when_absent(tmp_path):
    make_video(tmp_path, "a.mp4")
    p = write_show(tmp_path, "show:\n  - {id: a, source: a.mp4}\n")
    show = load_show(p)
    assert show.transition is TransitionMode.CUT
    assert show.duration == 0.8


def test_transition_and_duration_parsed(tmp_path):
    make_video(tmp_path, "a.mp4")
    p = write_show(tmp_path, "transition: crossfade\nduration: 1.5\nshow:\n  - {id: a, source: a.mp4}\n")
    show = load_show(p)
    assert show.transition is TransitionMode.CROSSFADE
    assert show.duration == 1.5


def test_transition_is_case_insensitive(tmp_path):
    make_video(tmp_path, "a.mp4")
    p = write_show(tmp_path, "transition: Wipe\nshow:\n  - {id: a, source: a.mp4}\n")
    assert load_show(p).transition is TransitionMode.WIPE


def test_unknown_transition_raises(tmp_path):
    make_video(tmp_path, "a.mp4")
    p = write_show(tmp_path, "transition: swirl\nshow:\n  - {id: a, source: a.mp4}\n")
    with pytest.raises(ShowError, match="transition"):
        load_show(p)


def test_non_positive_duration_raises(tmp_path):
    make_video(tmp_path, "a.mp4")
    p = write_show(tmp_path, "duration: 0\nshow:\n  - {id: a, source: a.mp4}\n")
    with pytest.raises(ShowError, match="duration"):
        load_show(p)


def test_non_numeric_duration_raises(tmp_path):
    make_video(tmp_path, "a.mp4")
    p = write_show(tmp_path, "duration: soon\nshow:\n  - {id: a, source: a.mp4}\n")
    with pytest.raises(ShowError, match="duration"):
        load_show(p)


def test_missing_file_raises(tmp_path):
    with pytest.raises(ShowError, match="not found"):
        load_show(tmp_path / "nope.yaml")


def test_invalid_yaml_raises(tmp_path):
    p = write_show(tmp_path, "show: [unclosed")
    with pytest.raises(ShowError, match="invalid YAML"):
        load_show(p)


def test_empty_show_raises(tmp_path):
    p = write_show(tmp_path, "show: []\n")
    with pytest.raises(ShowError, match="non-empty"):
        load_show(p)


def test_duplicate_ids_raise(tmp_path):
    make_video(tmp_path, "a.mp4")
    p = write_show(tmp_path, "show:\n  - {id: x, source: a.mp4}\n  - {id: x, source: a.mp4}\n")
    with pytest.raises(ShowError, match="duplicate cue id: x"):
        load_show(p)


def test_missing_source_file_raises(tmp_path):
    p = write_show(tmp_path, "show:\n  - {id: intro, source: ghost.mp4}\n")
    with pytest.raises(ShowError, match="intro"):
        load_show(p)


def test_cue_missing_keys_raises(tmp_path):
    p = write_show(tmp_path, "show:\n  - {id: intro}\n")
    with pytest.raises(ShowError, match="'id' and 'source'"):
        load_show(p)


def test_tail_dissolve_transition_parsed(tmp_path):
    make_video(tmp_path, "a.mp4")
    p = write_show(tmp_path, "transition: tail_dissolve\nshow:\n  - {id: a, source: a.mp4}\n")
    assert load_show(p).transition is TransitionMode.TAIL_DISSOLVE

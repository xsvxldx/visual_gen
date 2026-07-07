import pytest

from visualgen.config import Config, ConfigError, MidiTrigger, load_config


def test_missing_file_returns_defaults(tmp_path):
    cfg = load_config(tmp_path / "config.yaml")
    assert cfg == Config(
        midi_port=None,
        next_trigger=MidiTrigger("note_on", note=60, channel=None),
        previous_trigger=MidiTrigger("note_on", note=61, channel=None),
        fallback=None,
    )


def test_full_config(tmp_path):
    (tmp_path / "safe.mp4").write_bytes(b"\x00")
    p = tmp_path / "config.yaml"
    p.write_text(
        "midi:\n"
        "  port: \"IAC Driver Bus 1\"\n"
        "  next: {type: note_on, note: 40, channel: 2}\n"
        "  previous: {type: note_on, note: 41}\n"
        "fallback: safe.mp4\n"
    )
    cfg = load_config(p)
    assert cfg.midi_port == "IAC Driver Bus 1"
    assert cfg.next_trigger == MidiTrigger("note_on", note=40, channel=2)
    assert cfg.previous_trigger == MidiTrigger("note_on", note=41, channel=None)
    assert cfg.fallback == (tmp_path / "safe.mp4").resolve()


def test_missing_fallback_file_raises(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("fallback: ghost.mp4\n")
    with pytest.raises(ConfigError, match="fallback"):
        load_config(p)


def test_unsupported_trigger_type_raises(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("midi:\n  next: {type: control_change, control: 7}\n")
    with pytest.raises(ConfigError, match="note_on"):
        load_config(p)


def test_invalid_yaml_raises(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("midi: [oops")
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config(p)

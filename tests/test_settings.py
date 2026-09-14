from lmssdr.core.module import DEFAULT_PORTS, MAX_PORTS
from lmssdr.core.settings import Settings


def test_defaults():
    s = Settings()
    assert s.port_count == DEFAULT_PORTS == 32
    assert s.restore_routing_on_start is True


def test_round_trip():
    s = Settings.load()
    s.port_count = 48
    s.theme_name = "Crimson"
    s.save()
    assert Settings.load().port_count == 48
    assert Settings.load().theme_name == "Crimson"


def test_port_count_is_clamped_on_load():
    s = Settings.load()
    s.port_count = 9999
    s.save()
    assert Settings.load().port_count == MAX_PORTS


def test_unknown_keys_are_ignored():
    """A settings file from a future version must not stop this one loading."""
    path = Settings.path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"port_count": 8, "something_new": true}')
    assert Settings.load().port_count == 8


def test_corrupt_file_falls_back_to_defaults():
    path = Settings.path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("]]]")
    assert Settings.load().port_count == DEFAULT_PORTS


def test_legacy_settings_file_is_renamed_on_load():
    from lmssdr.core.paths import config_dir
    legacy = config_dir() / "lmsdr.settings.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text('{"port_count": 12}')

    assert Settings.load().port_count == 12
    assert Settings.path().exists()
    assert not legacy.exists()


def test_file_names_are_namespaced():
    assert Settings.path().name == "lmssdr.settings.json"


def test_the_whole_config_directory_migrates(tmp_path, monkeypatch):
    """The directory was called lmssdr too, and it is renamed as a unit."""
    import json
    from lmssdr.core.paths import config_dir

    base = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(base))
    old = base / "lmsdr"
    old.mkdir(parents=True)
    (old / "lmsdr.settings.json").write_text(json.dumps({"port_count": 17}))

    assert Settings.load().port_count == 17
    assert config_dir().name == "lmssdr"
    assert Settings.path().exists()
    assert not old.exists()


def test_directory_migration_does_not_merge_two_configs(tmp_path, monkeypatch):
    import json
    base = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(base))
    (base / "lmsdr").mkdir(parents=True)
    (base / "lmsdr" / "lmsdr.settings.json").write_text(json.dumps({"port_count": 8}))
    (base / "lmssdr").mkdir(parents=True)
    (base / "lmssdr" / "lmssdr.settings.json").write_text(json.dumps({"port_count": 40}))

    assert Settings.load().port_count == 40      # the current one wins
    assert (base / "lmsdr").exists()             # the old one is left alone


# -- window size ---------------------------------------------------------

def test_window_size_defaults_fit_a_32_port_matrix():
    s = Settings()
    assert s.window_width == 1000 and s.window_height == 900


def test_window_size_round_trips():
    s = Settings.load()
    s.window_width, s.window_height = 1440, 1024
    s.save()
    again = Settings.load()
    assert (again.window_width, again.window_height) == (1440, 1024)


# -- mute settings --------------------------------------------------------

def test_mute_is_off_by_default():
    """It takes control of a microphone; that is not a default."""
    s = Settings()
    assert s.mute_enabled is False
    assert s.mute_source == ""
    assert s.mute_transport_port == -1 and s.mute_talkback_port == -1


def test_mackie_defaults():
    s = Settings()
    assert (s.mute_transport_channel, s.mute_play_note, s.mute_stop_note) == (1, 94, 93)
    assert (s.mute_talkback_channel, s.mute_talkback_cc) == (14, 14)
    assert s.mute_transport_velocity == 127


def test_mute_settings_round_trip():
    s = Settings.load()
    s.mute_enabled = True
    s.mute_source = "alsa_input.example"
    s.mute_transport_port = 3
    s.mute_talkback_port = 3
    s.mute_play_note = 60
    s.save()
    again = Settings.load()
    assert again.mute_enabled is True
    assert again.mute_source == "alsa_input.example"
    assert again.mute_transport_port == 3 and again.mute_talkback_port == 3
    assert again.mute_play_note == 60

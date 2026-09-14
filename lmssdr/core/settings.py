"""Persisted application settings.

Stored as JSON under $XDG_CONFIG_HOME/lmssdr/lmssdr.settings.json. Port names
live in lmssdr.ports.json and routing in lmssdr.routing.json; this file is only
what does not belong to either.

The files carry the application name even though they already sit in an
lmssdr directory, so that a copy lifted out of that directory -- into a backup,
a gist, a bug report -- still says what it belongs to.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from .module import DEFAULT_PORTS, clamp_ports
from .paths import (config_dir, migrate, migrate_config_dir,
                    read_json, write_json)

FILE_NAME = "lmssdr.settings.json"
#: What this file was called in earlier versions, newest
#: first. Renamed on load, one hop at a time.
LEGACY_FILE_NAMES = ("lmsdr.settings.json", "settings.json")


@dataclass
class Settings:
    #: How many snd_seq_dummy ports to provide. Applying this reloads the
    #: kernel module, so it is deliberately not applied on every keystroke --
    #: the interface has an explicit Apply.
    port_count: int = DEFAULT_PORTS

    #: Last window size, remembered so the app reopens as you left it. The
    #: defaults are sized to show a 32-port matrix whole; they are clamped to
    #: the screen at load, because a remembered size from a larger monitor
    #: must not open off the edge of a smaller one.
    window_width: int = 1000
    window_height: int = 900

    start_minimised: bool = True

    #: Offer to record connections found at start-up when nothing is saved.
    #: That is the one moment the app can still see routes built before it
    #: was installed: once anything is saved, start-up becomes authoritative
    #: and sweeps them.
    warn_about_found_routes: bool = True

    #: Re-assert saved routing when the application starts. On by default:
    #: subscriptions do not survive a reboot or a module reload, and a router
    #: that forgets its routes on restart is not much of a router.
    #:
    #: Authoritative, like the Apply button: connections between dummy ports
    #: that are not in the saved routing are removed. Turn this off to leave
    #: the sequencer exactly as found at launch.
    restore_routing_on_start: bool = True

    # -- MIDI-driven microphone mute -------------------------------------
    #
    # Off by default: it takes control of a microphone, which is not
    # something to start doing because the application was installed.
    mute_enabled: bool = False
    #: PulseAudio source name, not an index -- indices are reassigned when
    #: devices come and go.
    mute_source: str = ""
    #: Dummy port numbers, -1 for unset. The talkback port may equal the
    #: transport port; one cable can carry both.
    mute_transport_port: int = -1
    mute_talkback_port: int = -1

    # The rules, defaulting to Mackie Control transport. Fields rather than
    # constants so a DAW that cannot speak Mackie can still drive this.
    mute_transport_channel: int = 1
    mute_play_note: int = 94
    mute_stop_note: int = 93
    mute_transport_velocity: int = 127
    mute_talkback_channel: int = 14
    mute_talkback_cc: int = 14

    # Appearance
    theme_mode: str = "system"        # system | light | dark
    theme_name: str = "Ocean"
    text_size: str = "default"

    # -- persistence -----------------------------------------------------

    @classmethod
    def path(cls) -> Path:
        return config_dir() / FILE_NAME

    @classmethod
    def load(cls) -> "Settings":
        migrate_config_dir()
        for legacy in LEGACY_FILE_NAMES:
            migrate(config_dir() / legacy, cls.path())
        raw = read_json(cls.path(), {})
        if not isinstance(raw, dict):
            return cls()
        known = {f.name for f in cls.__dataclass_fields__.values()}
        clean = {k: v for k, v in raw.items() if k in known}
        settings = cls(**clean)
        settings.port_count = clamp_ports(settings.port_count)
        return settings

    def save(self) -> None:
        write_json(self.path(), asdict(self))

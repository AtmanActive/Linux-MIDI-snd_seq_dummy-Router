"""Linux-MIDI-snd_seq_dummy-Router - control and route ALSA's dummy MIDI ports."""

#: Single source of truth for the version. pyproject.toml reads this
#: attribute rather than carrying its own copy, so they cannot drift.
__version__ = "1.0.4"

#: Display name, as shown in the window title, tray tooltip and dialogs.
APP_TITLE = "LMSSDR MIDI Router"

#: Longer name, for places with room for it (about box, desktop entry).
APP_FULL_NAME = "Linux-MIDI-snd_seq_dummy-Router"

#: Project homepage. pyproject.toml reads this too, so there is one copy.
APP_HOMEPAGE = "https://github.com/AtmanActive/Linux-MIDI-snd_seq_dummy-Router"

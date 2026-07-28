"""The ctypes layer: what can be checked without acting on the desktop.

Only pure functions are exercised. Everything that injects input (`type_text`,
`click`, `hotkey`) would really act on the machine running the suite: a test
that "checks that Ctrl+W works" closes a window along the way. Those functions
therefore stay uncovered, and the README says so.
"""

from __future__ import annotations

import pytest

from winctl import winapi


class TestKeyNormalisation:
    @pytest.mark.parametrize(
        "french,english",
        [
            ("entree", "enter"),
            ("echap", "escape"),
            ("suppr", "delete"),
            ("haut", "up"),
            ("bas", "down"),
            ("gauche", "left"),
            ("droite", "right"),
            ("maj", "shift"),
            ("espace", "space"),
            ("retour", "backspace"),
            ("fin", "end"),
            ("verrmaj", "capslock"),
        ],
    )
    def test_the_french_names_match_their_english_equivalents(self, french, english):
        """The point of the aliases: not forcing anyone to know the Windows names."""
        assert winapi.normalize_key(french) == winapi.normalize_key(english)

    @pytest.mark.parametrize("form", ["ENTER", " enter ", "En_Ter", "Enter"])
    def test_case_spaces_and_underscores_are_ignored(self, form):
        assert winapi.normalize_key(form) == winapi.normalize_key("enter")

    def test_letters_and_digits_are_covered(self):
        assert winapi.normalize_key("a") == ord("A")
        assert winapi.normalize_key("Z") == ord("Z")
        assert winapi.normalize_key("7") == ord("7")

    @pytest.mark.parametrize("key,code", [("f1", 0x70), ("f12", 0x7B), ("f24", 0x87)])
    def test_all_the_function_keys_exist(self, key, code):
        assert winapi.normalize_key(key) == code

    def test_an_unknown_key_raises_with_examples(self):
        """The error message reaches the model: it has to be actionable."""
        with pytest.raises(ValueError) as error:
            winapi.normalize_key("magic-key")

        message = str(error.value)
        assert "magic-key" in message
        assert "enter" in message and "f1-f24" in message

    def test_an_empty_string_raises(self):
        with pytest.raises(ValueError):
            winapi.normalize_key("")


class TestExtendedFlag:
    @pytest.mark.parametrize("key", ["up", "down", "left", "right", "delete", "insert", "win"])
    def test_the_editing_pad_keys_are_marked_extended(self, key):
        """Without KEYEVENTF_EXTENDEDKEY, the arrows come out as numeric-keypad keys."""
        assert winapi.normalize_key(key) in winapi._EXTENDED

    @pytest.mark.parametrize("key", ["a", "enter", "space", "tab", "shift"])
    def test_the_ordinary_keys_are_not(self, key):
        assert winapi.normalize_key(key) not in winapi._EXTENDED


class TestModifiers:
    def test_every_modifier_alias_is_a_valid_key(self):
        for alias in winapi.MODIFIER_ALIASES:
            assert winapi.normalize_key(alias)


class TestDpiAwareness:
    def test_enable_dpi_awareness_returns_a_known_mode(self):
        """Callable without harm: the server calls it at import time."""
        assert winapi.enable_dpi_awareness() in {"per-monitor-v2", "per-monitor", "system", "none"}


class TestWindows:
    def test_list_windows_returns_usable_windows(self):
        windows = winapi.list_windows()

        assert windows, "at least one window is open on an interactive desktop"
        for window in windows:
            data = window.as_dict()
            assert set(data) >= {"hwnd", "title", "process", "bounds"}
            assert data["hwnd"]

    def test_find_window_on_an_absurd_title_returns_none(self):
        assert winapi.find_window("zzz-no-window-has-this-title-zzz") is None

    def test_the_virtual_desktop_has_a_positive_size(self):
        vs = winapi.virtual_screen()

        assert vs.width > 0 and vs.height > 0

    def test_the_cursor_position_is_inside_the_virtual_desktop(self):
        x, y = winapi.cursor_position()
        vs = winapi.virtual_screen()

        assert vs.left <= x <= vs.left + vs.width
        assert vs.top <= y <= vs.top + vs.height

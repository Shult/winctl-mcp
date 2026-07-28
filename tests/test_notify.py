"""Configuration loading and notification dispatch.

Most of this file covers `load_env`, and that is not disproportionate: it is the
only place in the project where a failure would be completely silent. A
configuration that is never loaded raises nothing -- it shows up as a
`send_summary` falling back to a Windows balloon nobody is watching, several
days before anyone notices.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from winctl import notify


class TestEnvFileLocation:
    """The .env location is declared, never guessed."""

    def test_no_candidate_derives_from_the_package_location(self, tmp_path, monkeypatch):
        """The trap this module must make impossible.

        Deriving a candidate from `Path(__file__).resolve().parents[2]` points at
        the repository root while working from the sources -- and at some
        site-packages directory as soon as the package is installed. The failure
        would be mute: no error, just a configuration that is never read.
        """
        monkeypatch.chdir(tmp_path)
        package = Path(notify.__file__).resolve()

        candidates = [c.resolve() for c in notify.env_candidates()]

        assert candidates == [tmp_path.resolve() / ".env"], (
            "without an explicit path nor WINCTL_ENV_FILE, the only candidate is the current directory"
        )
        assert package.parents[2] / ".env" not in candidates, "no candidate derived from the package tree"
        for candidate in candidates:
            assert package.parent not in candidate.parents, "no candidate inside the installed package"

    def test_the_explicit_path_wins(self, tmp_path, monkeypatch):
        elsewhere = tmp_path / "elsewhere.env"
        elsewhere.write_text("TELEGRAM_BOT_TOKEN=explicit\n", encoding="utf-8")
        (tmp_path / ".env").write_text("TELEGRAM_BOT_TOKEN=cwd\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv(notify.ENV_PATH_VAR, str(tmp_path / ".env"))

        used = notify.load_env(elsewhere)

        assert used == elsewhere
        assert os.environ["TELEGRAM_BOT_TOKEN"] == "explicit"

    def test_the_environment_variable_wins_over_the_current_directory(self, tmp_path, monkeypatch):
        """This is the form that follows an MCP server: it is inherited by children."""
        declared = tmp_path / "config" / "prod.env"
        declared.parent.mkdir()
        declared.write_text("TELEGRAM_CHAT_ID=42\n", encoding="utf-8")
        (tmp_path / ".env").write_text("TELEGRAM_CHAT_ID=999\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv(notify.ENV_PATH_VAR, str(declared))

        assert notify.load_env() == declared
        assert os.environ["TELEGRAM_CHAT_ID"] == "42"

    def test_fallback_on_the_current_directory(self, env_file):
        path = env_file("TELEGRAM_CHAT_ID=7\n")

        assert notify.load_env() == path
        assert os.environ["TELEGRAM_CHAT_ID"] == "7"

    def test_a_declared_but_missing_path_loads_nothing(self, tmp_path, monkeypatch):
        """A wrong WINCTL_ENV_FILE must not crash the MCP server.

        `notification_status` is there to make the mistake visible: it reports
        the file actually loaded, or the list of locations tried.
        """
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv(notify.ENV_PATH_VAR, str(tmp_path / "does-not-exist.env"))

        assert notify.load_env() is None

    def test_status_reports_the_loaded_file(self, env_file):
        path = env_file("TELEGRAM_BOT_TOKEN=x\nTELEGRAM_CHAT_ID=1\n")

        assert notify.status()["env_file"] == str(path)

    def test_status_reports_the_locations_tried_when_nothing_is_found(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        report = notify.status()["env_file"]

        assert "no .env" in report
        assert str(tmp_path) in report

    def test_the_tilde_is_expanded(self, tmp_path, monkeypatch):
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / "home.env").write_text("TELEGRAM_CHAT_ID=home\n", encoding="utf-8")
        monkeypatch.setenv(notify.ENV_PATH_VAR, "~/home.env")

        assert notify.load_env() == tmp_path / "home.env"
        assert os.environ["TELEGRAM_CHAT_ID"] == "home"


class TestReloading:
    """load_env is called again on every action: rereading must stay sound."""

    def test_empty_values_are_ignored(self, env_file):
        env_file("TELEGRAM_BOT_TOKEN=token\nTELEGRAM_CHAT_ID=\n")

        notify.load_env()

        assert os.environ["TELEGRAM_BOT_TOKEN"] == "token"
        assert "TELEGRAM_CHAT_ID" not in os.environ, (
            "an empty line must not freeze the variable: filling in the .env must be enough"
        )

    def test_filling_in_the_env_needs_no_restart(self, env_file):
        path = env_file("TELEGRAM_BOT_TOKEN=token\nTELEGRAM_CHAT_ID=\n")
        notify.load_env()
        assert not notify.telegram_configured()

        path.write_text("TELEGRAM_BOT_TOKEN=token\nTELEGRAM_CHAT_ID=123\n", encoding="utf-8")
        notify.load_env()

        assert notify.telegram_configured()

    def test_a_line_removed_from_the_env_removes_the_variable(self, env_file):
        path = env_file("TELEGRAM_BOT_TOKEN=token\nTELEGRAM_CHAT_ID=123\n")
        notify.load_env()

        path.write_text("TELEGRAM_BOT_TOKEN=token\n", encoding="utf-8")
        notify.load_env()

        assert "TELEGRAM_CHAT_ID" not in os.environ

    def test_the_parent_environment_wins_over_the_env_file(self, env_file, monkeypatch):
        """A setting passed through `claude mcp add --env` must keep the last word."""
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "from-parent")
        env_file("TELEGRAM_CHAT_ID=from-file\n")

        notify.load_env()

        assert os.environ["TELEGRAM_CHAT_ID"] == "from-parent"


class TestConfiguredChannels:
    def test_telegram_requires_both_keys(self, monkeypatch):
        assert not notify.telegram_configured()
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
        assert not notify.telegram_configured()
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
        assert notify.telegram_configured()

    def test_email_requires_host_and_recipient(self, monkeypatch):
        monkeypatch.setenv("SMTP_HOST", "smtp.example.net")
        assert not notify.email_configured()
        monkeypatch.setenv("SMTP_TO", "me@example.net")
        assert notify.email_configured()

    def test_default_channel_without_any_configuration(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert notify.status()["default_channel"] == "local toast"

    def test_telegram_wins_over_email(self, env_file):
        env_file("TELEGRAM_BOT_TOKEN=x\nTELEGRAM_CHAT_ID=1\nSMTP_HOST=h\nSMTP_TO=t\n")
        assert notify.status()["default_channel"] == "telegram"


class TestSending:
    def test_an_unknown_channel_is_refused(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(notify.NotifyError, match="Unknown channel"):
            notify.send("text", channel="pigeon")

    def test_unconfigured_telegram_raises_before_any_network_call(self, tmp_path, monkeypatch):
        """The error must be explicit, not an HTTP call traceback."""
        monkeypatch.chdir(tmp_path)
        with pytest.raises(notify.NotifyError, match="TELEGRAM_BOT_TOKEN"):
            notify.telegram_send("text")

    def test_unconfigured_email_raises_before_any_network_call(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(notify.NotifyError, match="SMTP_HOST"):
            notify.email_send("text", "subject")

    def test_telegram_edit_without_configuration_returns_false(self, tmp_path, monkeypatch):
        """A display failure must never fail the caller."""
        monkeypatch.chdir(tmp_path)
        assert notify.telegram_edit(1, "text") is False

    def test_without_any_channel_the_local_fallback_warns(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        calls = []
        monkeypatch.setattr(notify, "toast", lambda title, text: calls.append((title, text)) or {})

        result = notify.send("summary", subject="subject")

        assert calls == [("subject", "summary")]
        assert "TELEGRAM_BOT_TOKEN" in result["warning"], (
            "the silent fallback is the trap: the user must learn why"
        )


class TestTruncation:
    @pytest.mark.parametrize("limit", [50, 1024, 4096])
    def test_an_overlong_text_is_truncated_under_the_limit(self, limit):
        out = notify._clip("a" * (limit * 2), limit)
        assert len(out) <= limit
        assert "truncated" in out

    def test_a_short_text_is_left_intact(self):
        assert notify._clip("hello", 100) == "hello"

"""Check that the `conftest` guardrails are actually armed.

These tests do not test the project: they test the suite. If one of them fails,
the others can no longer be trusted -- they could send a real Telegram message
or a real email from the developer's machine.
"""

from __future__ import annotations

import os

import httpx
import pytest

from winctl import notify

from .conftest import NetworkForbidden


class TestNetworkBlocked:
    def test_httpx_client_raises(self):
        with pytest.raises(NetworkForbidden):
            httpx.Client()

    def test_httpx_get_raises(self):
        with pytest.raises(NetworkForbidden):
            httpx.get("https://api.telegram.org/")

    def test_telegram_send_does_not_leave(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "dummy-token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")

        with pytest.raises(NetworkForbidden):
            notify.telegram_send("this must never be sent")

    def test_telegram_edit_does_not_leave(self, monkeypatch):
        """telegram_edit catches httpx.HTTPError and ValueError, not our guard.

        The error must propagate: confusing it with a refusal from Telegram
        would turn a network leak into a silent `return False`.
        """
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "dummy-token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")

        with pytest.raises(NetworkForbidden):
            notify.telegram_edit(1, "text")

    def test_telegram_discover_does_not_leave(self, env_file):
        env_file("TELEGRAM_BOT_TOKEN=dummy-token\n")

        with pytest.raises(NetworkForbidden):
            notify.telegram_discover_chat_id()

    def test_smtp_is_blocked(self):
        import smtplib

        with pytest.raises(NetworkForbidden):
            smtplib.SMTP("localhost")

    def test_email_send_does_not_leave(self, monkeypatch):
        monkeypatch.setenv("SMTP_HOST", "smtp.example.net")
        monkeypatch.setenv("SMTP_TO", "me@example.net")

        with pytest.raises(NetworkForbidden):
            notify.email_send("text", "subject")


class TestIsolatedEnvironment:
    def test_the_configuration_keys_are_removed(self):
        """A real .env on the developer's machine must not skew the suite."""
        for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "SMTP_HOST", "WINCTL_READONLY"):
            assert os.getenv(key) is None

    def test_the_global_state_of_notify_is_clean(self):
        assert notify._EXTERNAL_KEYS is None
        assert notify._LOADED_KEYS == set()

"""Guardrails and shared tooling for the whole suite.

This suite runs on the machine the project drives, and the `notify` module knows
how to reach Telegram and an SMTP server. A test that forgot to stub that layer
would send a real message -- noise at best, at worst hijacking the long-polling
of a bot in service (the Telegram API allows a single getUpdates reader per bot,
the others get a 409 error).

The `autouse` fixtures below make that accident impossible rather than merely
unlikely: `httpx` and `smtplib` raise as soon as they are touched.

Nothing here drives the mouse or the keyboard: the suite only tests pure
functions and screen captures, which are read-only. The input injection
functions (winapi.type_text, click...) are not exercised, since that cannot be
done without really acting on the desktop -- a deliberate choice, documented in
the README.
"""

from __future__ import annotations

import socket

import httpx
import pytest

import winctl.notify as notify


class NetworkForbidden(RuntimeError):
    """Raised as soon as a test attempts an outgoing HTTP request."""


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Neutralise httpx (and SMTP) for the whole duration of each test."""

    def forbidden(*args, **kwargs):
        raise NetworkForbidden("Network calls are forbidden in tests (see tests/conftest.py).")

    for name in (
        "Client", "AsyncClient", "request", "stream",
        "get", "post", "put", "patch", "delete", "head", "options",
    ):
        if hasattr(httpx, name):
            monkeypatch.setattr(httpx, name, forbidden)

    import smtplib

    monkeypatch.setattr(smtplib, "SMTP", forbidden)
    monkeypatch.setattr(smtplib, "SMTP_SSL", forbidden)


@pytest.fixture(autouse=True)
def no_stray_env(monkeypatch):
    """Isolate the tests from a real .env lying around on the machine.

    The modules read os.environ directly: without this, a desktop where Telegram
    is configured would pass tests that are meant to check the absence of
    configuration.
    """
    for key in (
        "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
        "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM", "SMTP_TO",
        notify.ENV_PATH_VAR, "WINCTL_READONLY",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def clean_notify_state():
    """Reset the global state of `notify` between two tests.

    `_EXTERNAL_KEYS` is computed only once, on the first load_env: without this
    reset, the first test to load a .env would freeze for all the following ones
    the list of variables "coming from the parent", and the execution order
    would change the results.
    """
    notify._EXTERNAL_KEYS = None
    notify._LOADED_KEYS.clear()
    notify._LOADED_FROM = None
    yield
    notify._EXTERNAL_KEYS = None
    notify._LOADED_KEYS.clear()
    notify._LOADED_FROM = None


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    """Write a .env in a temporary directory that becomes the cwd.

    The cwd is always moved: a load_env test run from the repository root could
    otherwise find the developer's real .env.
    """
    monkeypatch.chdir(tmp_path)

    def write(content: str, name: str = ".env"):
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        return path

    return write


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]

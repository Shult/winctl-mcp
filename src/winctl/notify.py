"""Notification channels: Telegram, SMTP email, local Windows notification.

Telegram is the default channel because it is the only one that can be set up in
two minutes without OAuth, without a verified domain and without prior review:
creating a bot with @BotFather immediately yields a usable token.
"""

from __future__ import annotations

import os
import smtplib
import subprocess
from email.message import EmailMessage
from pathlib import Path

import httpx
from dotenv import dotenv_values

TELEGRAM_API = "https://api.telegram.org"

# Environment variable naming the .env file to load.
#
# It exists because the alternative -- guessing the location -- cannot work.
# winctl is meant to be *installed*: once the package sits in a site-packages
# directory or a global tool environment, looking for a .env "next to the code"
# only points at an installation directory, where nobody will ever write their
# configuration. And an MCP server is started by its client (Claude Code, for
# instance) with the working directory of the session: the .env is no more
# likely to be under the cwd.
#
# The location must therefore be declared, not guessed. The calling program
# passes it to load_env(), or sets it in this variable -- which has the
# advantage of being inherited by child processes, and so follows an MCP server
# started down a chain.
ENV_PATH_VAR = "WINCTL_ENV_FILE"

# Variables present in the environment before the first load: they come from the
# parent process and always keep priority over the .env file.
_EXTERNAL_KEYS: frozenset[str] | None = None
# Variables that load_env has written, so they can be removed if the matching
# line disappears or becomes empty in the .env file.
_LOADED_KEYS: set[str] = set()
# Last file actually loaded, reported by status(): when the configuration seems
# ignored, the first question is always "which .env?".
_LOADED_FROM: Path | None = None


def env_candidates(explicit: str | os.PathLike[str] | None = None) -> list[Path]:
    """Locations to look for the .env, from highest to lowest priority.

    No candidate is derived from the package location: that is deliberately
    excluded (see ENV_PATH_VAR). The fallback on the current directory only
    serves the simple case -- running winctl from the folder holding its .env.
    """
    out: list[Path] = []
    if explicit:
        out.append(Path(explicit).expanduser())
    from_env = os.getenv(ENV_PATH_VAR, "").strip()
    if from_env:
        out.append(Path(from_env).expanduser())
    out.append(Path.cwd() / ".env")
    return out


def env_file(explicit: str | os.PathLike[str] | None = None) -> Path | None:
    """First existing candidate, or None if no .env is found."""
    for candidate in env_candidates(explicit):
        if candidate.is_file():
            return candidate
    return None


def load_env(path: str | os.PathLike[str] | None = None) -> Path | None:
    """(Re)load the .env; callable at any time. Returns the file used.

    `path` takes priority over everything else: that is the preferred form when
    the calling program knows where its configuration lives.

    Empty values are ignored: a `TELEGRAM_CHAT_ID=` line present at startup no
    longer freezes the variable, so filling in the .env is enough -- no server
    restart needed.
    """
    global _EXTERNAL_KEYS, _LOADED_FROM
    if _EXTERNAL_KEYS is None:
        _EXTERNAL_KEYS = frozenset(k for k, v in os.environ.items() if v)

    chosen = env_file(path)
    _LOADED_FROM = chosen
    values = {k: v for k, v in dotenv_values(chosen).items() if v} if chosen else {}

    for key in _LOADED_KEYS - values.keys():
        os.environ.pop(key, None)
        _LOADED_KEYS.discard(key)
    for key, value in values.items():
        if key not in _EXTERNAL_KEYS:
            os.environ[key] = value
            _LOADED_KEYS.add(key)
    return chosen


class NotifyError(RuntimeError):
    pass


_TRUNCATION_NOTICE = "\n[... message truncated]"


def _clip(text: str, limit: int) -> str:
    """Bring a text under `limit` characters, truncation notice included.

    The notice length is computed rather than written by hand: the Telegram API
    rejects the whole message when the limit is exceeded (1024 for a caption,
    4096 for a message), so an approximation here turns into a failed send.
    """
    if len(text) <= limit:
        return text
    return text[: max(0, limit - len(_TRUNCATION_NOTICE))] + _TRUNCATION_NOTICE


# --------------------------------------------------------------------------
# Telegram
# --------------------------------------------------------------------------


def telegram_configured() -> bool:
    return bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))


def telegram_send(text: str, image: bytes | None = None, image_mime: str = "jpeg") -> dict:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise NotifyError(
            "Telegram is not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID "
            "in the .env file (see the Notifications section of the README)."
        )

    with httpx.Client(timeout=25.0) as client:
        if image:
            # A photo caption is capped at 1024 characters by the API: beyond
            # that, send the photo, then the full text in a separate message.
            caption = _clip(text, 1024)
            resp = client.post(
                f"{TELEGRAM_API}/bot{token}/sendPhoto",
                data={"chat_id": chat_id, "caption": caption},
                files={"photo": (f"screenshot.{image_mime}", image, f"image/{image_mime}")},
            )
            payload = resp.json()
            if not payload.get("ok"):
                raise NotifyError(f"Telegram refused the photo: {payload.get('description', resp.text)}")
            if len(text) > 1024:
                client.post(
                    f"{TELEGRAM_API}/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": _clip(text, 4096)},
                )
            return {"channel": "telegram", "with_image": True, "message_id": payload["result"]["message_id"]}

        resp = client.post(
            f"{TELEGRAM_API}/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": _clip(text, 4096)},
        )
        payload = resp.json()
        if not payload.get("ok"):
            raise NotifyError(f"Telegram refused the message: {payload.get('description', resp.text)}")
        return {"channel": "telegram", "with_image": False, "message_id": payload["result"]["message_id"]}


def telegram_edit(message_id: int, text: str) -> bool:
    """Rewrite an already sent message; returns False if Telegram refuses.

    Useful to publish the progress of a long task in a single message rather
    than stacking one per step. An edit can fail for harmless reasons (identical
    text, message too old, message deleted by hand): False is returned instead
    of raising, because a display failure must not fail the caller.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                f"{TELEGRAM_API}/bot{token}/editMessageText",
                json={"chat_id": chat_id, "message_id": message_id, "text": _clip(text, 4096)},
            )
        return bool(resp.json().get("ok"))
    except (httpx.HTTPError, ValueError):
        return False


def telegram_discover_chat_id() -> dict:
    """Read the bot's recent updates to recover the conversation id."""
    load_env()
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise NotifyError("TELEGRAM_BOT_TOKEN is missing from the .env file. Create a bot with @BotFather first.")
    with httpx.Client(timeout=25.0) as client:
        me = client.get(f"{TELEGRAM_API}/bot{token}/getMe").json()
        if not me.get("ok"):
            raise NotifyError(f"Invalid token: {me.get('description')}")
        updates = client.get(f"{TELEGRAM_API}/bot{token}/getUpdates").json()

    chats = {}
    for upd in updates.get("result", []):
        msg = upd.get("message") or upd.get("channel_post") or {}
        chat = msg.get("chat")
        if chat:
            chats[chat["id"]] = chat.get("title") or chat.get("username") or chat.get("first_name", "")

    return {
        "bot": me["result"].get("username"),
        "chats": [{"chat_id": k, "name": v} for k, v in chats.items()],
        "hint": (
            "No conversation found: open Telegram, send any message to the bot "
            f"@{me['result'].get('username')}, then run this tool again."
            if not chats
            else "Copy the chat_id you want into TELEGRAM_CHAT_ID in the .env file."
        ),
    }


# --------------------------------------------------------------------------
# Email
# --------------------------------------------------------------------------


def email_configured() -> bool:
    return bool(os.getenv("SMTP_HOST") and os.getenv("SMTP_TO"))


def email_send(text: str, subject: str, image: bytes | None = None, image_mime: str = "jpeg") -> dict:
    host = os.getenv("SMTP_HOST")
    to_addr = os.getenv("SMTP_TO")
    if not host or not to_addr:
        raise NotifyError(
            "Email is not configured. Set SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, "
            "SMTP_FROM and SMTP_TO in the .env file."
        )
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "")
    password = os.getenv("SMTP_PASSWORD", "")
    from_addr = os.getenv("SMTP_FROM") or user or to_addr

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(text)
    if image:
        msg.add_attachment(image, maintype="image", subtype=image_mime, filename=f"screenshot.{image_mime}")

    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=30) as server:
            if user:
                server.login(user, password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls()
            if user:
                server.login(user, password)
            server.send_message(msg)

    return {"channel": "email", "to": to_addr, "with_image": bool(image)}


# --------------------------------------------------------------------------
# Local Windows notification (zero-configuration fallback)
# --------------------------------------------------------------------------


def toast(title: str, text: str) -> dict:
    """Show a system balloon through NotifyIcon.

    Chosen over the WinRT ToastNotification API because it requires neither an
    extra PowerShell module nor a registered application identifier.
    """
    script = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$n = New-Object System.Windows.Forms.NotifyIcon;"
        "$n.Icon = [System.Drawing.SystemIcons]::Information;"
        "$n.BalloonTipTitle = $args[0];"
        "$n.BalloonTipText = $args[1];"
        "$n.Visible = $true;"
        "$n.ShowBalloonTip(15000);"
        "Start-Sleep -Seconds 6;"
        "$n.Dispose()"
    )
    subprocess.Popen(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script, title, _clip(text, 250)],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return {"channel": "windows_toast", "note": "Notification displayed locally on the PC."}


# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------


def send(
    text: str,
    channel: str = "auto",
    subject: str = "winctl summary",
    image: bytes | None = None,
    image_mime: str = "jpeg",
) -> dict:
    load_env()
    channel = channel.lower()

    if channel == "auto":
        if telegram_configured():
            channel = "telegram"
        elif email_configured():
            channel = "email"
        else:
            result = toast(subject, text)
            result["warning"] = (
                "Neither Telegram nor email is configured: the summary was only displayed on the PC. "
                "Set TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID in the .env file to receive it remotely."
            )
            return result

    if channel == "telegram":
        return telegram_send(text, image, image_mime)
    if channel in ("email", "mail"):
        return email_send(text, subject, image, image_mime)
    if channel in ("toast", "windows", "local"):
        return toast(subject, text)
    raise NotifyError(f"Unknown channel: {channel!r}. Expected: auto, telegram, email or toast.")


def status() -> dict:
    load_env()
    return {
        "telegram": "configured" if telegram_configured() else "not configured",
        "email": "configured" if email_configured() else "not configured",
        "windows_toast": "always available",
        "default_channel": "telegram" if telegram_configured() else ("email" if email_configured() else "local toast"),
        # Answers the only useful question when the configuration seems ignored.
        "env_file": str(_LOADED_FROM) if _LOADED_FROM else (
            f"no .env found (searched: {', '.join(str(p) for p in env_candidates())})"
        ),
    }

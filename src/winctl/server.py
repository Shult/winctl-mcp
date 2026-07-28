"""The "winctl" MCP server: full control of a Windows desktop.

Every coordinate exchanged is in real pixels of the virtual desktop. On a
multi-monitor setup, the origin (0, 0) is the top-left corner of the primary
monitor; a monitor placed to its left therefore has negative x coordinates.
"""

from __future__ import annotations

import os
import subprocess
import time

from mcp.server.fastmcp import FastMCP, Image

from . import apps, capture, notify, winapi

notify.load_env()
DPI_MODE = winapi.enable_dpi_awareness()

mcp = FastMCP(
    "winctl",
    log_level="WARNING",
    instructions=(
        "Full control of a Windows PC. Recommended method: call screenshot to see the screen, "
        "act, then capture again to check the result before chaining another action. "
        "Coordinates are in real pixels of the virtual desktop and may be negative on a "
        "multi-monitor setup (see screen_info). To type safely, pass the title of the target "
        "window in the `window` parameter: the action is cancelled if focus is not obtained, "
        "rather than typing into the wrong application."
    ),
)


READONLY_VAR = "WINCTL_READONLY"


def _readonly() -> bool:
    notify.load_env()
    return os.getenv(READONLY_VAR, "").strip().lower() in ("1", "true", "yes", "on")


def _guard() -> None:
    if _readonly():
        raise RuntimeError(
            f"Read-only mode is active ({READONLY_VAR}). Screenshots and reads are still "
            "possible, but every keyboard/mouse/system action is blocked. Remove the variable "
            "from the .env file to re-enable control."
        )


def _window_or_fail(title: str) -> winapi.WindowInfo:
    win = winapi.find_window(title)
    if not win:
        raise ValueError(
            f"No window matches {title!r}. Use list_windows to see the open titles."
        )
    return win


def _foreground_label() -> str:
    hwnd = winapi.foreground_window()
    for w in winapi.list_windows():
        if w.hwnd == hwnd:
            return f"{w.title} ({w.process})"
    return "unknown"


def _target(window: str | None) -> str:
    """Focus `window` before typing, and fail if focus is not obtained.

    Without this check, a keystroke meant for an editor could land in the
    browser or the active terminal: a clean error is preferable to an action
    silently sent to the wrong place.
    """
    if window is None:
        return _foreground_label()
    win = _window_or_fail(window)
    if not winapi.focus_window(win.hwnd):
        raise RuntimeError(
            f"Could not bring \"{win.title}\" to the foreground; the input was cancelled to "
            f"avoid typing into the wrong window (currently: {_foreground_label()}). "
            f"A window running as administrator or in exclusive fullscreen can block the switch."
        )
    time.sleep(0.15)
    return f"{win.title} ({win.process})"


# ==========================================================================
# Screen
# ==========================================================================


@mcp.tool(structured_output=False)
def screenshot(
    monitor: int = 0,
    max_width: int = 1400,
    grid: bool = False,
    grid_step: int = 200,
    region_x: int | None = None,
    region_y: int | None = None,
    region_width: int | None = None,
    region_height: int | None = None,
    image_format: str = "jpeg",
) -> list:
    """Capture the screen and return the image.

    monitor: 0 = all monitors combined, 1..N = a specific monitor (see screen_info).
    grid: overlays a grid annotated with real screen coordinates, very useful to
    aim a click precisely. region_*: captures a specific area in virtual-desktop
    coordinates, which gives far more detail than a downscaled full screen when
    small text has to be read.
    """
    region = None
    if None not in (region_x, region_y, region_width, region_height):
        region = {"x": region_x, "y": region_y, "width": region_width, "height": region_height}

    shot = capture.grab(
        monitor=monitor,
        region=region,
        max_width=max_width,
        fmt=image_format,
        grid=grid,
        grid_step=grid_step,
    )
    return [Image(data=shot.png, format=shot.mime), shot.summary()]


@mcp.tool(structured_output=False)
def screenshot_window(title: str, max_width: int = 1400, grid: bool = False) -> list:
    """Capture only the window whose title (or process) matches `title`.

    The window is brought to the foreground before the capture, otherwise
    whatever covers it would be photographed instead.
    """
    win = _window_or_fail(title)
    warning = ""
    if _readonly():
        warning = " (read-only mode: the window was not brought to the foreground, it may be partially hidden)"
    elif not winapi.focus_window(win.hwnd):
        warning = " (WARNING: the window could not be brought to the foreground, the image may show what covers it)"
    else:
        time.sleep(0.25)
    shot = capture.grab_window(win.hwnd, max_width=max_width, grid=grid)
    return [
        Image(data=shot.png, format=shot.mime),
        f"Window \"{win.title}\" ({win.process}){warning}. {shot.summary()}",
    ]


@mcp.tool()
def screen_info() -> dict:
    """List the monitors, their coordinates, and the current cursor position."""
    x, y = winapi.cursor_position()
    vs = winapi.virtual_screen()
    return {
        "monitors": capture.monitors(),
        "virtual_desktop": {"x": vs.left, "y": vs.top, "width": vs.width, "height": vs.height},
        "cursor": {"x": x, "y": y},
        "dpi_awareness": DPI_MODE,
        "readonly_mode": _readonly(),
    }


# ==========================================================================
# Mouse
# ==========================================================================


@mcp.tool()
def mouse_move(x: int, y: int, smooth: bool = False) -> dict:
    """Move the cursor to absolute coordinates. smooth=True mimics a human movement."""
    _guard()
    fx, fy = winapi.move_mouse(x, y, smooth=smooth)
    return {"cursor": {"x": fx, "y": fy}}


@mcp.tool()
def mouse_click(
    x: int | None = None,
    y: int | None = None,
    button: str = "left",
    clicks: int = 1,
    smooth: bool = False,
) -> dict:
    """Click, moving first if x and y are given.

    button: left, right, middle, x1, x2. clicks=2 for a double click.
    """
    _guard()
    if x is not None and y is not None:
        winapi.move_mouse(x, y, smooth=smooth)
        time.sleep(0.04)
    winapi.click(button=button, clicks=clicks)
    cx, cy = winapi.cursor_position()
    return {"clicked": {"x": cx, "y": cy}, "button": button, "clicks": clicks}


@mcp.tool()
def mouse_drag(
    from_x: int, from_y: int, to_x: int, to_y: int, button: str = "left", duration: float = 0.5
) -> dict:
    """Drag and drop from one point to another.

    The path is interpolated: an instant jump is often ignored by applications,
    which expect a sequence of movements to arm the drag.
    """
    _guard()
    winapi.move_mouse(from_x, from_y)
    time.sleep(0.08)
    winapi.mouse_down(button)
    time.sleep(0.08)
    winapi.move_mouse(to_x, to_y, smooth=True, duration=max(0.15, duration))
    time.sleep(0.08)
    winapi.mouse_up(button)
    return {"from": {"x": from_x, "y": from_y}, "to": {"x": to_x, "y": to_y}, "button": button}


@mcp.tool()
def mouse_scroll(clicks: int, horizontal: bool = False, x: int | None = None, y: int | None = None) -> dict:
    """Scroll by `clicks` notches (positive = up / right).

    The wheel acts on the window under the cursor: position it via x/y if
    several scrollable areas are visible.
    """
    _guard()
    if x is not None and y is not None:
        winapi.move_mouse(x, y)
        time.sleep(0.04)
    winapi.scroll(clicks, horizontal=horizontal)
    return {"scrolled": clicks, "axis": "horizontal" if horizontal else "vertical"}


# ==========================================================================
# Keyboard
# ==========================================================================


@mcp.tool()
def type_text(text: str, window: str | None = None, wpm: float = 0.0) -> dict:
    """Type text, accented characters and emoji included.

    Injection is Unicode based, hence independent from the keyboard layout:
    'é', 'ç' or '€' come out correctly on AZERTY as well as QWERTY.

    Set `window` (title or process) to explicitly target a window: it is brought
    to the foreground and typing is cancelled if focus fails. Without `window`,
    the keystrokes go to the active window, whatever it is.
    """
    _guard()
    target = _target(window)
    n = winapi.type_text(text, wpm=wpm)
    return {"typed_chars": n, "window": target}


@mcp.tool()
def press_key(key: str, presses: int = 1, window: str | None = None) -> dict:
    """Press a single key, optionally repeated.

    Examples: enter, escape, tab, delete, down, f5, space.
    """
    _guard()
    target = _target(window)
    winapi.press_key(key, presses=presses)
    return {"key": key, "presses": presses, "window": target}


@mcp.tool()
def hotkey(keys: list[str], window: str | None = None) -> dict:
    """Send a keyboard shortcut, keys held down simultaneously.

    Examples: ["ctrl","c"], ["alt","tab"], ["ctrl","shift","escape"], ["win","d"].
    """
    _guard()
    target = _target(window)
    winapi.hotkey(keys)
    return {"hotkey": "+".join(keys), "window": target}


@mcp.tool()
def paste_text(text: str, window: str | None = None) -> dict:
    """Insert a long text through the clipboard, then Ctrl+V.

    Much faster than character-by-character typing beyond a few hundred
    characters, and immune to applications that drop keystrokes.
    Overwrites the clipboard contents.
    """
    _guard()
    target = _target(window)
    winapi.set_clipboard(text)
    time.sleep(0.1)
    winapi.hotkey(["ctrl", "v"])
    return {"pasted_chars": len(text), "window": target}


@mcp.tool()
def clipboard(action: str = "read", text: str = "") -> dict:
    """Read or write the clipboard. action: read or write."""
    if action == "read":
        return {"text": winapi.get_clipboard()}
    if action == "write":
        _guard()
        winapi.set_clipboard(text)
        return {"written_chars": len(text)}
    raise ValueError(f"Unknown action: {action!r}. Expected: read or write.")


# ==========================================================================
# Windows
# ==========================================================================


@mcp.tool()
def list_windows(filter: str = "") -> dict:
    """List the open windows with their position, size and process.

    `filter` narrows the result to titles or processes containing that text.
    """
    wins = winapi.list_windows()
    q = filter.lower().strip()
    if q:
        wins = [w for w in wins if q in w.title.lower() or q in w.process.lower()]
    return {"count": len(wins), "windows": [w.as_dict() for w in wins]}


@mcp.tool()
def focus_window(title: str) -> dict:
    """Bring to the foreground the window matching the given title or process."""
    _guard()
    win = _window_or_fail(title)
    if not winapi.focus_window(win.hwnd):
        raise RuntimeError(
            f"Windows refused to bring \"{win.title}\" to the foreground (current window: "
            f"{_foreground_label()}). Do not chain keystrokes: they would go elsewhere."
        )
    return {
        "matched": win.title,
        "process": win.process,
        "focused": True,
        "bounds": win.as_dict()["bounds"],
    }


@mcp.tool()
def window_action(title: str, action: str) -> dict:
    """Act on a window. action: minimize, maximize, restore, close, hide."""
    _guard()
    win = _window_or_fail(title)
    winapi.set_window_state(win.hwnd, action)
    return {"matched": win.title, "action": action}


@mcp.tool()
def move_window(
    title: str, x: int, y: int, width: int | None = None, height: int | None = None
) -> dict:
    """Move and resize a window (useful to place it on a specific monitor)."""
    _guard()
    win = _window_or_fail(title)
    winapi.move_window(win.hwnd, x, y, width, height)
    return {"matched": win.title, "moved_to": {"x": x, "y": y, "width": width, "height": height}}


# ==========================================================================
# Applications and system
# ==========================================================================


@mcp.tool()
def launch_app(name: str, args: list[str] | None = None, cwd: str | None = None) -> dict:
    """Launch an application by common name, full path, or URL.

    Accepts "spotify", "chrome", "notepad", an .exe path, or an https:// address.
    Microsoft Store applications are supported.
    """
    _guard()
    return apps.launch(name, args=args, cwd=cwd)


@mcp.tool()
def list_installed_apps(query: str = "") -> dict:
    """List the Start menu applications, filtered by `query`.

    Use it when launch_app cannot find a name, to recover the exact label.
    """
    results = apps.search_installed(query)
    return {"count": len(results), "apps": results}


@mcp.tool()
def run_powershell(command: str, timeout: int = 60) -> dict:
    """Run a PowerShell command and return its output.

    This is the escape hatch for everything the other tools do not cover:
    services, registry, network, files, volume, shutdown.
    """
    _guard()
    proc = subprocess.run(
        [
            "powershell", "-NoProfile", "-NonInteractive", "-Command",
            # Force UTF-8 output, otherwise every accented character comes back mis-decoded.
            f"[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; {command}",
        ],
        capture_output=True,
        timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    decode = lambda b: b.decode("utf-8", errors="replace").strip()  # noqa: E731
    return {
        "exit_code": proc.returncode,
        "stdout": decode(proc.stdout)[:20000],
        "stderr": decode(proc.stderr)[:4000],
    }


@mcp.tool()
def wait(seconds: float) -> dict:
    """Wait before the next action (application loading, animation, web page)."""
    seconds = max(0.0, min(seconds, 120.0))
    time.sleep(seconds)
    return {"waited": seconds}


# ==========================================================================
# Notifications
# ==========================================================================


@mcp.tool()
def send_summary(
    text: str,
    channel: str = "auto",
    attach_screenshot: bool = False,
    subject: str = "winctl summary",
    monitor: int = 0,
) -> dict:
    """Send a summary to the user, outside of the agent session.

    channel: auto (Telegram if configured, else email, else local notification),
    telegram, email, or toast. attach_screenshot attaches a screen capture.
    """
    image = None
    mime = "jpeg"
    if attach_screenshot:
        shot = capture.grab(monitor=monitor, max_width=1600, fmt="jpeg", quality=80)
        image, mime = shot.png, shot.mime
    return notify.send(text, channel=channel, subject=subject, image=image, image_mime=mime)


@mcp.tool()
def notification_status() -> dict:
    """Report which notification channels are configured."""
    return notify.status()


@mcp.tool()
def telegram_find_chat_id() -> dict:
    """Setup helper: recover the chat_id after writing to the Telegram bot."""
    return notify.telegram_discover_chat_id()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

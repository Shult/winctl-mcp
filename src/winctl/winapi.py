"""Low-level access layer to the Windows API.

Everything goes through SendInput rather than higher-level helpers: it is the
only reliable way to inject accented characters independently from the active
keyboard layout (KEYEVENTF_UNICODE), and to aim correctly on a multi-monitor
desktop whose origin is negative (MOUSEEVENTF_VIRTUALDESK).
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from dataclasses import dataclass

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

if ctypes.sizeof(ctypes.c_void_p) == 8:
    ULONG_PTR = ctypes.c_ulonglong
else:
    ULONG_PTR = ctypes.c_ulong


# --------------------------------------------------------------------------
# DPI awareness
# --------------------------------------------------------------------------

DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)


def enable_dpi_awareness() -> str:
    """Must be called before any capture or click.

    Without it Windows lies about coordinates and screen sizes as soon as one
    monitor runs at a scaling other than 100%.
    """
    try:
        if user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2):
            return "per-monitor-v2"
    except AttributeError:
        pass
    try:
        shcore = ctypes.WinDLL("shcore", use_last_error=True)
        if shcore.SetProcessDpiAwareness(2) == 0:
            return "per-monitor"
    except Exception:
        pass
    try:
        if user32.SetProcessDPIAware():
            return "system"
    except Exception:
        pass
    return "none"


# --------------------------------------------------------------------------
# SendInput structures
# --------------------------------------------------------------------------

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_XDOWN = 0x0080
MOUSEEVENTF_XUP = 0x0100
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008

WHEEL_DELTA = 120

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTunion(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTunion)]


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT

# ctypes assumes a c_int return value: without these declarations, every
# HANDLE/HWND is truncated to 32 bits and becomes invalid in a 64-bit process.
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetClipboardData.argtypes = (wintypes.UINT,)
user32.GetClipboardData.restype = wintypes.HANDLE
user32.SetClipboardData.argtypes = (wintypes.UINT, wintypes.HANDLE)
user32.SetClipboardData.restype = wintypes.HANDLE
user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.SendMessageW.restype = ctypes.c_void_p
kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
kernel32.GlobalAlloc.argtypes = (wintypes.UINT, ctypes.c_size_t)
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = (wintypes.HGLOBAL,)
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = (wintypes.HGLOBAL,)


class InputError(RuntimeError):
    """Raised when Windows refuses the input injection."""


def _send(*inputs: INPUT) -> None:
    n = len(inputs)
    arr = (INPUT * n)(*inputs)
    sent = user32.SendInput(n, arr, ctypes.sizeof(INPUT))
    if sent != n:
        err = ctypes.get_last_error()
        hint = ""
        if err == 5:
            hint = (
                " (ERROR_ACCESS_DENIED: the target window is probably running as "
                "administrator. Restart the MCP client / server as administrator "
                "to drive that window.)"
            )
        raise InputError(f"SendInput failed after {sent}/{n} events, code {err}.{hint}")


# --------------------------------------------------------------------------
# Virtual screen and mouse
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class VirtualScreen:
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height


def virtual_screen() -> VirtualScreen:
    return VirtualScreen(
        left=user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
        top=user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
        width=user32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
        height=user32.GetSystemMetrics(SM_CYVIRTUALSCREEN),
    )


def _to_absolute(x: int, y: int) -> tuple[int, int]:
    """Convert virtual-desktop pixels to the normalised 0-65535 space.

    The origin of the virtual desktop can be negative (a monitor to the left of
    the primary one), hence subtracting vs.left / vs.top before normalising.
    """
    vs = virtual_screen()
    x = max(vs.left, min(x, vs.right - 1))
    y = max(vs.top, min(y, vs.bottom - 1))
    nx = int(round((x - vs.left) * 65535 / max(vs.width - 1, 1)))
    ny = int(round((y - vs.top) * 65535 / max(vs.height - 1, 1)))
    return nx, ny


def cursor_position() -> tuple[int, int]:
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def _mouse_event(flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> INPUT:
    return INPUT(
        type=INPUT_MOUSE,
        mi=MOUSEINPUT(dx=dx, dy=dy, mouseData=data, dwFlags=flags, time=0, dwExtraInfo=0),
    )


def move_mouse(x: int, y: int, smooth: bool = False, duration: float = 0.25) -> tuple[int, int]:
    """Move the cursor to absolute virtual-desktop coordinates."""
    if smooth:
        sx, sy = cursor_position()
        steps = max(2, int(duration / 0.008))
        for i in range(1, steps + 1):
            t = i / steps
            eased = t * t * (3 - 2 * t)  # smoothstep: gradual start and stop
            ix = int(round(sx + (x - sx) * eased))
            iy = int(round(sy + (y - sy) * eased))
            nx, ny = _to_absolute(ix, iy)
            _send(_mouse_event(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, nx, ny))
            time.sleep(duration / steps)
    else:
        nx, ny = _to_absolute(x, y)
        _send(_mouse_event(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, nx, ny))
    return cursor_position()


_BUTTONS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, 0),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP, 0),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP, 0),
    "x1": (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, 1),
    "x2": (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, 2),
}


def click(button: str = "left", clicks: int = 1, interval: float = 0.06) -> None:
    try:
        down, up, data = _BUTTONS[button]
    except KeyError:
        raise ValueError(f"Unknown button: {button!r}. Expected: {', '.join(_BUTTONS)}") from None
    for i in range(clicks):
        if i:
            time.sleep(interval)
        _send(_mouse_event(down, data=data), _mouse_event(up, data=data))


def mouse_down(button: str = "left") -> None:
    down, _, data = _BUTTONS[button]
    _send(_mouse_event(down, data=data))


def mouse_up(button: str = "left") -> None:
    _, up, data = _BUTTONS[button]
    _send(_mouse_event(up, data=data))


def scroll(amount: int, horizontal: bool = False) -> None:
    """amount is in wheel notches; positive = up (or right)."""
    flag = MOUSEEVENTF_HWHEEL if horizontal else MOUSEEVENTF_WHEEL
    _send(_mouse_event(flag, data=amount * WHEEL_DELTA))


# --------------------------------------------------------------------------
# Keyboard
# --------------------------------------------------------------------------

# French aliases sit next to the English names on purpose: an AZERTY user
# naturally writes "entree" or "suppr", and rejecting those names would only
# add a lookup step for no benefit.
VK: dict[str, int] = {
    "backspace": 0x08, "retour": 0x08, "tab": 0x09, "tabulation": 0x09,
    "clear": 0x0C, "enter": 0x0D, "return": 0x0D, "entree": 0x0D,
    "shift": 0x10, "maj": 0x10, "ctrl": 0x11, "control": 0x11,
    "alt": 0x12, "pause": 0x13, "capslock": 0x14, "verrmaj": 0x14,
    "esc": 0x1B, "escape": 0x1B, "echap": 0x1B,
    "space": 0x20, "espace": 0x20, "spacebar": 0x20,
    "pageup": 0x21, "pagedown": 0x22, "end": 0x23, "fin": 0x23,
    "home": 0x24, "origine": 0x24,
    "left": 0x25, "gauche": 0x25, "up": 0x26, "haut": 0x26,
    "right": 0x27, "droite": 0x27, "down": 0x28, "bas": 0x28,
    "select": 0x29, "print": 0x2A, "execute": 0x2B, "printscreen": 0x2C,
    "insert": 0x2D, "inser": 0x2D, "delete": 0x2E, "suppr": 0x2E, "del": 0x2E,
    "help": 0x2F,
    "win": 0x5B, "winleft": 0x5B, "windows": 0x5B, "super": 0x5B, "cmd": 0x5B,
    "winright": 0x5C, "apps": 0x5D, "menu": 0x5D,
    "numpad0": 0x60, "numpad1": 0x61, "numpad2": 0x62, "numpad3": 0x63,
    "numpad4": 0x64, "numpad5": 0x65, "numpad6": 0x66, "numpad7": 0x67,
    "numpad8": 0x68, "numpad9": 0x69,
    "multiply": 0x6A, "add": 0x6B, "separator": 0x6C,
    "subtract": 0x6D, "decimal": 0x6E, "divide": 0x6F,
    "numlock": 0x90, "scrolllock": 0x91,
    "shiftleft": 0xA0, "shiftright": 0xA1,
    "ctrlleft": 0xA2, "ctrlright": 0xA3,
    "altleft": 0xA4, "altright": 0xA5, "altgr": 0xA5, "altgraph": 0xA5,
    "volumemute": 0xAD, "volumedown": 0xAE, "volumeup": 0xAF,
    "nexttrack": 0xB0, "prevtrack": 0xB1, "stopmedia": 0xB2, "playpause": 0xB3,
}
for _i in range(1, 25):
    VK[f"f{_i}"] = 0x6F + _i
for _c in "0123456789":
    VK[_c] = ord(_c)
for _c in "abcdefghijklmnopqrstuvwxyz":
    VK[_c] = ord(_c.upper())

# Keys that require KEYEVENTF_EXTENDEDKEY: without that flag, the arrows and the
# editing pad are interpreted as their numeric-keypad equivalents.
_EXTENDED = {
    0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28,
    0x2C, 0x2D, 0x2E, 0x5B, 0x5C, 0x5D, 0x6F, 0x90,
    0xA3, 0xA5, 0xAD, 0xAE, 0xAF, 0xB0, 0xB1, 0xB2, 0xB3,
}

MODIFIER_ALIASES = {"ctrl", "control", "shift", "maj", "alt", "altgr", "altgraph", "win", "windows", "super", "cmd"}


def normalize_key(key: str) -> int:
    k = key.strip().lower().replace(" ", "").replace("_", "")
    if k not in VK:
        raise ValueError(
            f"Unknown key: {key!r}. Valid examples: enter, ctrl, alt, shift, "
            f"escape, tab, f1-f24, delete, up/down/left/right, win, a-z, 0-9."
        )
    return VK[k]


def _key_event(vk: int, up: bool) -> INPUT:
    scan = user32.MapVirtualKeyW(vk, 0)
    flags = KEYEVENTF_KEYUP if up else 0
    if vk in _EXTENDED:
        flags |= KEYEVENTF_EXTENDEDKEY
    return INPUT(
        type=INPUT_KEYBOARD,
        ki=KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0),
    )


def key_down(key: str) -> None:
    _send(_key_event(normalize_key(key), up=False))


def key_up(key: str) -> None:
    _send(_key_event(normalize_key(key), up=True))


def press_key(key: str, presses: int = 1, interval: float = 0.03) -> None:
    vk = normalize_key(key)
    for i in range(presses):
        if i:
            time.sleep(interval)
        _send(_key_event(vk, False), _key_event(vk, True))


def hotkey(keys: list[str], hold: float = 0.03) -> None:
    """Press the keys in order, then release them in reverse order."""
    vks = [normalize_key(k) for k in keys]
    try:
        for vk in vks:
            _send(_key_event(vk, False))
            time.sleep(0.012)
        time.sleep(hold)
    finally:
        for vk in reversed(vks):
            try:
                _send(_key_event(vk, True))
            except InputError:
                pass
            time.sleep(0.008)


def _unicode_events(ch: str) -> list[INPUT]:
    """A character outside the BMP takes two UTF-16 units: inject them separately."""
    events: list[INPUT] = []
    raw = ch.encode("utf-16-le")
    units = [int.from_bytes(raw[i : i + 2], "little") for i in range(0, len(raw), 2)]
    for unit in units:
        for up in (False, True):
            flags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0)
            events.append(
                INPUT(
                    type=INPUT_KEYBOARD,
                    ki=KEYBDINPUT(wVk=0, wScan=unit, dwFlags=flags, time=0, dwExtraInfo=0),
                )
            )
    return events


#: Pause between two characters. Modern controls (WinUI / Text Services
#: Framework, including the Windows 11 Notepad) lose the contents of bursts of
#: Unicode events: past the first few characters, they all take the value of the
#: last one. One SendInput call per character, spaced by a minimal pause,
#: delivers the text intact everywhere. For long texts, prefer going through the
#: clipboard.
CHAR_DELAY = 0.003


def type_text(text: str, wpm: float = 0.0, char_delay: float | None = None) -> int:
    """Type text as raw Unicode.

    Independent from the keyboard layout: 'é', 'ç' or '€' come out identical on
    AZERTY and QWERTY. Line breaks are converted to Enter, because
    KEYEVENTF_UNICODE does not inject a usable newline.
    """
    typed = 0
    delay = CHAR_DELAY if char_delay is None else char_delay
    if wpm > 0:
        delay = max(delay, 60.0 / (wpm * 5.0))

    for ch in text:
        if ch == "\n":
            press_key("enter")
        elif ch == "\r":
            continue
        elif ch == "\t":
            press_key("tab")
        else:
            _send(*_unicode_events(ch))
        if delay:
            time.sleep(delay)
        typed += 1
    return typed


# --------------------------------------------------------------------------
# Windows
# --------------------------------------------------------------------------

SW_HIDE, SW_NORMAL, SW_MINIMIZE, SW_MAXIMIZE, SW_RESTORE = 0, 1, 6, 3, 9
WM_CLOSE = 0x0010
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    process: str
    pid: int
    rect: tuple[int, int, int, int]
    minimized: bool
    foreground: bool = False

    def as_dict(self) -> dict:
        left, top, right, bottom = self.rect
        return {
            "hwnd": self.hwnd,
            "title": self.title,
            "process": self.process,
            "pid": self.pid,
            "bounds": {"x": left, "y": top, "width": right - left, "height": bottom - top},
            "center": [(left + right) // 2, (top + bottom) // 2],
            "minimized": self.minimized,
            "foreground": self.foreground,
        }


def _process_name(pid: int) -> str:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value.rsplit("\\", 1)[-1]
        return ""
    finally:
        kernel32.CloseHandle(handle)


def list_windows(visible_only: bool = True, with_title_only: bool = True) -> list[WindowInfo]:
    found: list[WindowInfo] = []
    fg = user32.GetForegroundWindow()

    def callback(hwnd, _lparam):
        if visible_only and not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value
        if with_title_only and not title.strip():
            return True
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        found.append(
            WindowInfo(
                hwnd=hwnd,
                title=title,
                process=_process_name(pid.value),
                pid=pid.value,
                rect=(rect.left, rect.top, rect.right, rect.bottom),
                minimized=bool(user32.IsIconic(hwnd)),
                foreground=(hwnd == fg),
            )
        )
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return found


def find_window(query: str) -> WindowInfo | None:
    """Search by title then by process name, preferring exact matches."""
    q = query.lower()
    windows = list_windows()
    for w in windows:
        if w.title.lower() == q:
            return w
    for w in windows:
        if q in w.title.lower():
            return w
    for w in windows:
        if q in w.process.lower():
            return w
    return None


def foreground_window() -> int:
    return user32.GetForegroundWindow()


def _attempt_focus(hwnd: int) -> None:
    """Combine the three workarounds for the Windows foreground lock.

    Windows only grants SetForegroundWindow to the process that emitted the last
    user input. We therefore make ourselves eligible by synthesising an ALT
    keystroke, then attach our input queue to that of the active window so that
    the call is considered to come from the same context.
    """
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)

    vk_menu = 0x12
    _send(_key_event(vk_menu, False))
    _send(_key_event(vk_menu, True))

    fg = user32.GetForegroundWindow()
    target_thread = user32.GetWindowThreadProcessId(hwnd, None)
    current_thread = kernel32.GetCurrentThreadId()
    fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0

    attached = []
    for t in {fg_thread, target_thread}:
        if t and t != current_thread and user32.AttachThreadInput(current_thread, t, True):
            attached.append(t)
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetActiveWindow(hwnd)
    finally:
        for t in attached:
            user32.AttachThreadInput(current_thread, t, False)


def focus_window(hwnd: int, retries: int = 3, settle: float = 0.25) -> bool:
    """Bring a window to the foreground and confirm the result.

    The outcome is verified rather than assumed: typing into the wrong window is
    the worst possible failure for this server, so the caller must be able to
    stop dead if focus was not obtained.
    """
    for attempt in range(retries):
        if user32.GetForegroundWindow() == hwnd:
            return True
        _attempt_focus(hwnd)
        time.sleep(settle * (attempt + 1))
    return user32.GetForegroundWindow() == hwnd


def set_window_state(hwnd: int, state: str) -> None:
    # French aliases, same rationale as the key names in VK.
    mapping = {
        "minimize": SW_MINIMIZE, "reduire": SW_MINIMIZE,
        "maximize": SW_MAXIMIZE, "agrandir": SW_MAXIMIZE,
        "restore": SW_RESTORE, "restaurer": SW_RESTORE,
        "normal": SW_NORMAL, "hide": SW_HIDE,
    }
    key = state.strip().lower()
    if key == "close" or key == "fermer":
        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        return
    if key not in mapping:
        raise ValueError(f"Unknown state: {state!r}. Expected: minimize, maximize, restore, normal, hide, close.")
    user32.ShowWindow(hwnd, mapping[key])


def move_window(hwnd: int, x: int, y: int, width: int | None = None, height: int | None = None) -> None:
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w = width if width is not None else rect.right - rect.left
    h = height if height is not None else rect.bottom - rect.top
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    user32.MoveWindow(hwnd, x, y, w, h, True)


# --------------------------------------------------------------------------
# Clipboard
# --------------------------------------------------------------------------

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def get_clipboard() -> str:
    for _ in range(10):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("Cannot open the clipboard (locked by another application).")
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return ""
        try:
            return ctypes.c_wchar_p(ptr).value or ""
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def set_clipboard(text: str) -> None:
    for _ in range(10):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("Cannot open the clipboard (locked by another application).")
    try:
        user32.EmptyClipboard()
        data = text.encode("utf-16-le") + b"\x00\x00"
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        ptr = kernel32.GlobalLock(handle)
        ctypes.memmove(ptr, data, len(data))
        kernel32.GlobalUnlock(handle)
        # The clipboard takes ownership of the block: do not free it ourselves.
        user32.SetClipboardData(CF_UNICODETEXT, handle)
    finally:
        user32.CloseClipboard()

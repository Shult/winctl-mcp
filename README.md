# winctl

**Give your agent the hands and eyes of a Windows user.**

`winctl` is a local MCP server that exposes the whole desktop: see the screen,
move the mouse, type on the keyboard, manipulate windows, launch applications,
run PowerShell, and send you a summary when it is done. No driver to install, no
service to keep running, no account to create — one Python package, one
registration line, and the agent sees your desktop.

Everything stays on the machine. Nothing leaves it, except the summaries you
explicitly ask for, to the channel you configure yourself.

![Demo](https://raw.githubusercontent.com/Shult/winctl-mcp/main/docs/demo.gif)

---

## Requirements

- **Windows 10 or 11.** The project is ctypes on top of the Win32 API: it runs
  on no other system, and that is not a temporary limitation.
- **Python 3.11 or later.**
- **An open interactive session.** Input injection needs a desktop: no Windows
  service, no container, no SSH without a graphical session.
- An MCP client. The examples use [Claude Code](https://claude.com/claude-code),
  but the server speaks standard MCP over stdio.

## Installation

With [uv](https://docs.astral.sh/uv/):

```bash
uv tool install winctl-mcp
```

Or from source:

```bash
git clone https://github.com/Shult/winctl-mcp
cd winctl-mcp
uv sync
```

Check that the command answers:

```bash
winctl-mcp --help
```

## Registering with Claude Code

```bash
claude mcp add winctl --scope user -- winctl-mcp
```

From source, point at the virtual environment interpreter:

```bash
claude mcp add winctl --scope user -- "C:\path\to\winctl-mcp\.venv\Scripts\python.exe" -m winctl.server
```

`--scope user` makes the server available in all your sessions, whatever the
working directory. Check it:

```bash
claude mcp list
```

The tools then appear under the `mcp__winctl__` prefix — for example
`mcp__winctl__screenshot`. The `winctl` name is the one you gave to
`claude mcp add`: if you register it under another name, the prefix follows.

Then ask the agent: "take a screenshot and tell me what you see".

---

## The tools

### See the screen

| Tool | Purpose |
| --- | --- |
| `screenshot` | Capture one monitor, all monitors, or a specific region |
| `screenshot_window` | Capture a given window, after bringing it to the foreground |
| `screen_info` | List the monitors, their coordinates, the cursor position |

Two options change everything on `screenshot`:

- **`grid: true`** overlays a grid annotated with real screen coordinates. It is
  the most reliable way to aim a click to the pixel.
- **`region_x/y/width/height`** captures a specific area. Far more legible than
  a downscaled full screen when small text has to be deciphered.

### Mouse and keyboard

| Tool | Purpose |
| --- | --- |
| `mouse_move`, `mouse_click`, `mouse_drag`, `mouse_scroll` | Pointer control |
| `type_text` | Type text, accented characters and emoji included |
| `press_key`, `hotkey` | Single key or combination (`["ctrl","c"]`) |
| `paste_text` | Insert through the clipboard, for long texts |
| `clipboard` | Read / write the clipboard |

Key names accept English as well as French: `enter`/`entree`, `escape`/`echap`,
`delete`/`suppr`, `up`/`haut`, `down`/`bas`, `left`/`gauche`, `right`/`droite`,
`shift`/`maj`, `space`/`espace`, `tab`, `f1`…`f24`, `win`.

### Windows, applications, system

| Tool | Purpose |
| --- | --- |
| `list_windows` | Open windows, with position, size and process |
| `focus_window`, `window_action`, `move_window` | Foreground, minimize / maximize / close, move |
| `launch_app` | Launch by common name, full path or URL |
| `list_installed_apps` | Find the exact name of an installed application |
| `run_powershell` | The escape hatch for everything else |
| `wait` | Pause between two actions |

`launch_app` accepts "spotify", "chrome", an `.exe` path or a URL. It chains
PATH, the *App Paths* registry key, then the Start menu — which also covers
Microsoft Store applications, since those have no directly addressable
executable.

### Notifications

| Tool | Purpose |
| --- | --- |
| `send_summary` | Send a summary, with a screenshot attached on request |
| `notification_status` | Report which channels are configured, and which `.env` was read |
| `telegram_find_chat_id` | Telegram setup helper |

`send_summary` exists for long tasks: the agent works, you do something else,
and the result lands on your phone. With no configuration, it falls back to a
local Windows notification balloon.

---

## Configuring notifications (optional)

Copy `.env.example` to `.env` and fill in what you need. No variable is
mandatory.

### Where winctl looks for the `.env`

It does not guess — that is deliberate. An MCP server is started by its client,
with the working directory of the session; and once `winctl` is installed as a
package, its code lives in a `site-packages` directory where nobody writes their
configuration. Looking "next to the code" or "under the current folder" is only
right by accident.

The location is therefore declared, in this order of priority:

1. the path passed to `notify.load_env(path)` by the calling program;
2. the **`WINCTL_ENV_FILE`** environment variable;
3. failing that, `.env` in the current working directory.

The robust form is the second one, set when registering the server:

```bash
claude mcp add winctl --scope user \
  --env WINCTL_ENV_FILE=C:\Users\you\.config\winctl\.env -- winctl-mcp
```

When in doubt, `notification_status` reports the file actually loaded, or the
list of locations tried.

The `.env` is reread on every action: completing the file does not require
restarting the server. A variable already present in the parent process
environment (through `--env`, for instance) always wins over the file.

### Telegram — recommended

It is the only channel that can be set up in two minutes: no OAuth, no domain to
verify, no prior review.

1. On Telegram, write to **@BotFather**, send `/newbot`, follow the steps.
2. Paste the resulting token into `TELEGRAM_BOT_TOKEN` in the `.env` file.
3. Send any message to your new bot.
4. Ask the agent: "call telegram_find_chat_id". Copy the returned identifier
   into `TELEGRAM_CHAT_ID`.

### Email

Fill in `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` and
`SMTP_TO`. With Gmail, use an
[app password](https://myaccount.google.com/apppasswords), not the account
password.

---

## Safety, and what this project cannot do

This section is long on purpose. A tool that hands control of a desktop to a
language model deserves precision about its edges.

**What you are granting.** An agent equipped with `winctl` can do to your
session anything you could do there: read your open windows, type into your
messaging app, delete files through `run_powershell`. There is no sandbox. That
is the point of the tool, and it is also its risk: do not register it on a
machine whose contents are not yours.

**Observation mode.** Set `WINCTL_READONLY=1` in the `.env` to allow only
captures and reads. Keyboard, mouse, window moves, application launches and
PowerShell are then refused with an explicit message. It is the right setting
for a first hands-on, or to let an agent diagnose without acting.

**Windows running as administrator.** Windows forbids a non-elevated process
from sending input to an elevated window: that is the *UIPI* mechanism, and
there is no clean way around it. If an application started as administrator
ignores keystrokes, this is why. The MCP client itself must be started as
administrator to drive it — with everything that implies.

**Windows only.** The `winapi` module is a direct ctypes binding on `user32`:
`SendInput`, `EnumWindows`, `SetForegroundWindow`. Nothing is portable, and
nothing is meant to become so.

**A graphical session is required.** Without an interactive desktop, `SendInput`
has nowhere to write. A server with no open session, a locked session or a
secure desktop (the UAC prompt, Ctrl+Alt+Del) are out of reach: those are
separate desktops, protected by the system.

**Targeting the right window.** The typing tools accept a `window` parameter.
The target window is brought to the foreground and **the action is cancelled if
focus fails**, rather than typing into the active application by mistake. Use it
systematically for any keystroke that matters.

**Multi-monitor.** Coordinates are in real pixels of the virtual desktop and may
be negative: a monitor placed to the left of the primary one has x coordinates
below zero. Call `screen_info` when in doubt rather than assuming.

**Games and exclusive fullscreen applications.** They often capture input at a
level `SendInput` does not reach, and their rendering can escape screen capture.
Borderless windowed mode generally works.

**Long texts.** Prefer `paste_text` over `type_text` beyond a few hundred
characters: it is instantaneous and immune to applications that drop keystrokes.

---

## Notable implementation details

These choices deserve an explanation, because they fix real failures observed in
use. If you hesitate to trust this code, this is the section to read.

**Character-by-character Unicode typing.** The keyboard goes through `SendInput`
with `KEYEVENTF_UNICODE`, which makes typing independent from the keyboard
layout — "é", "ç" or "€" come out identical on AZERTY and QWERTY. But modern
controls (WinUI / Text Services Framework, including the Windows 11 Notepad)
lose the contents of bursts: past the first few characters, they all take the
value of the last one. One `SendInput` call per character, spaced by 3 ms,
delivers the text intact everywhere.

**Focus verified, never assumed.** Windows only grants `SetForegroundWindow` to
the process that emitted the last user input. The server makes itself eligible
by synthesising an ALT keystroke, attaches its input queue to that of the active
window, then **checks the result** and retries. Typing into the wrong window is
the worst possible failure for this tool: a clean error beats a message sent to
the wrong conversation.

**DPI awareness enabled at startup.** Without
`SetProcessDpiAwarenessContext`, Windows lies about coordinates and screen sizes
as soon as one monitor is not at 100% scaling: the agent would aim right and
click beside.

**Grid in real coordinates, not image pixels.** Captures are resized to fit in
the model's context. Annotating the grid with image coordinates would force a
conversion back, hence a rounding error per click; the labels therefore carry
the clickable value directly. The summary attached to every capture restates the
conversion formula, for the cases where the model reasons on the image anyway.

**Interpolated mouse movement for drag and drop.** An instant jump from one
point to another is ignored by most applications, which expect a sequence of
movements to arm the drag. `mouse_drag` interpolates the path.

**The `.env` is reread on every action, never cached.** Completing the
configuration therefore does not require restarting the server — which matters
when it runs under a client one is reluctant to restart. Empty values are
ignored, and a line removed from the file removes the variable.

---

## Environment variable reference

All of them go in the `.env` (see `.env.example`). None is mandatory.

| Variable | Default | Purpose |
| --- | --- | --- |
| `WINCTL_ENV_FILE` | — | Path of the `.env` to load. Read from the environment, not from the `.env` |
| `WINCTL_READONLY` | — | `1` blocks keyboard, mouse, windows, applications and PowerShell |
| `TELEGRAM_BOT_TOKEN` | — | @BotFather token, for `send_summary` |
| `TELEGRAM_CHAT_ID` | — | Destination conversation |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_TO` | port `587` | Email channel of `send_summary` |

---

## Tests

```bash
uv sync --group dev
uv run pytest
```

The suite covers the pure functions (`.env` resolution, key normalisation,
notification dispatch), the geometry of captures on the real screen, and the MCP
server contract — its name, its tool list, and the tightness of read-only mode.

Two `autouse` guardrails are set in `tests/conftest.py` and checked by
`tests/test_guardrails.py`: `httpx` and `smtplib` raise as soon as they are
touched. The suite runs on the machine it drives; it must not be able to send a
real message.

**What is not covered, and why.** Input injection — `type_text`, `mouse_click`,
`hotkey` — is not tested automatically: a test checking that `Ctrl+W` works
closes a window along the way. Those functions are validated by hand. Likewise,
the capture tests assert nothing about the *content* of the image, only about
its structure: nothing may depend on what is displayed at the time of the test.

---

## Layout

```
src/winctl/
  server.py    definition of the 23 MCP tools
  winapi.py    ctypes layer: SendInput, windows, clipboard
  capture.py   screen captures, resizing, coordinate grid
  apps.py      application resolution and launching
  notify.py    Telegram, email, Windows notification, .env loading
```

`capture` and `notify` are not third-party libraries: they are the internals of
the server. `capture` backs the capture tools, `notify` backs `send_summary`.

---

## License

MIT — see [LICENSE](LICENSE).

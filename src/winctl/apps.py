"""Launching applications by common name.

A name such as "spotify" or "chrome" cannot be resolved from PATH alone. Several
sources are therefore tried in turn, from the cheapest to the slowest, and the
Start menu as a last resort also covers Microsoft Store applications, which have
no directly addressable executable.
"""

from __future__ import annotations

import functools
import json
import os
import shutil
import subprocess
import time
import winreg
from pathlib import Path

APP_PATHS_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"


def _from_app_paths(name: str) -> str | None:
    exe = name if name.lower().endswith(".exe") else f"{name}.exe"
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, f"{APP_PATHS_KEY}\\{exe}") as key:
                value, _ = winreg.QueryValueEx(key, "")
                if value and Path(value.strip('"')).exists():
                    return value.strip('"')
        except OSError:
            continue
    return None


@functools.lru_cache(maxsize=1)
def _start_apps_cached(bucket: int) -> list[dict]:
    """bucket only serves to invalidate the cache every 5 minutes."""
    try:
        proc = subprocess.run(
            [
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                # Without an explicit override, PowerShell emits in the OEM code
                # page and accented application names break the decoding.
                "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
                "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress",
            ],
            capture_output=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        data = json.loads(proc.stdout.decode("utf-8", errors="replace") or "[]")
        return data if isinstance(data, list) else [data]
    except Exception:
        return []


def start_apps() -> list[dict]:
    return _start_apps_cached(int(time.time() // 300))


def _from_start_menu(name: str) -> tuple[str, bool] | None:
    """Return (target, is_uwp). Exact matches first, then prefixes."""
    q = name.lower().strip()
    apps = start_apps()
    for matcher in (
        lambda n: n == q,
        lambda n: n.startswith(q),
        lambda n: q in n,
    ):
        for app in apps:
            if matcher(str(app.get("Name", "")).lower()):
                app_id = str(app.get("AppID", ""))
                is_uwp = "!" in app_id or not app_id.lower().endswith(".exe")
                return app_id, is_uwp
    return None


def resolve(name: str) -> dict:
    """Work out how to launch `name` without running it yet."""
    raw = name.strip().strip('"')

    if raw.startswith(("http://", "https://", "mailto:", "ms-settings:", "shell:")):
        return {"kind": "uri", "target": raw}

    p = Path(os.path.expandvars(raw))
    if p.exists():
        return {"kind": "path", "target": str(p.resolve())}

    on_path = shutil.which(raw)
    if on_path:
        return {"kind": "path", "target": on_path}

    reg = _from_app_paths(raw)
    if reg:
        return {"kind": "path", "target": reg}

    menu = _from_start_menu(raw)
    if menu:
        target, is_uwp = menu
        return {"kind": "uwp" if is_uwp else "path", "target": target}

    raise FileNotFoundError(
        f"Application not found: {name!r}. Try the full path to the executable, "
        f"or check the exact name with the list_installed_apps tool."
    )


def launch(name: str, args: list[str] | None = None, cwd: str | None = None, wait_ms: int = 800) -> dict:
    plan = resolve(name)
    args = args or []
    kind, target = plan["kind"], plan["target"]

    if kind == "uwp":
        # Store applications cannot be run directly: they go through the
        # AppsFolder pseudo-folder of the explorer.
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{target}"], creationflags=subprocess.CREATE_NO_WINDOW)
        pid = None
    elif kind == "uri":
        os.startfile(target)
        pid = None
    else:
        proc = subprocess.Popen(
            [target, *args],
            cwd=cwd,
            creationflags=subprocess.CREATE_NEW_CONSOLE if target.lower().endswith((".bat", ".cmd")) else 0,
        )
        pid = proc.pid

    if wait_ms:
        time.sleep(wait_ms / 1000)

    return {
        "launched": name,
        "resolved_as": target,
        "kind": kind,
        "pid": pid,
        "note": "The process is launched independently; it outlives the MCP server.",
    }


def search_installed(query: str = "", limit: int = 40) -> list[dict]:
    q = query.lower().strip()
    apps = start_apps()
    hits = [a for a in apps if not q or q in str(a.get("Name", "")).lower()]
    return [{"name": a.get("Name"), "app_id": a.get("AppID")} for a in hits[:limit]]

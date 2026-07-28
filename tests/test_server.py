"""The MCP server contract: its name, its tools, and read-only mode.

The server name and the tool list form the public interface: they are what the
agent sees (`mcp__winctl__screenshot`...) and what users write in their
configurations. Renaming them breaks their prompts without breaking the code --
so without anything warning about it. Hence this test.
"""

from __future__ import annotations

import asyncio

import pytest

from winctl import server

EXPECTED_TOOLS = {
    # Screen
    "screenshot", "screenshot_window", "screen_info",
    # Mouse
    "mouse_move", "mouse_click", "mouse_drag", "mouse_scroll",
    # Keyboard
    "type_text", "press_key", "hotkey", "paste_text", "clipboard",
    # Windows
    "list_windows", "focus_window", "window_action", "move_window",
    # Applications and system
    "launch_app", "list_installed_apps", "run_powershell", "wait",
    # Notifications
    "send_summary", "notification_status", "telegram_find_chat_id",
}


@pytest.fixture(scope="module")
def tools():
    return {tool.name: tool for tool in asyncio.run(server.mcp.list_tools())}


class TestMcpContract:
    def test_the_server_is_named_winctl(self):
        """This name prefixes the tools the agent sees."""
        assert server.mcp.name == "winctl"

    def test_the_tool_list_is_exactly_the_advertised_one(self, tools):
        assert set(tools) == EXPECTED_TOOLS

    def test_every_tool_is_documented(self, tools):
        """The description is what the agent reads to choose: it is not optional."""
        for name, tool in tools.items():
            assert tool.description and tool.description.strip(), name

    def test_the_server_instructions_state_the_method(self):
        assert "screenshot" in server.mcp.instructions
        assert "window" in server.mcp.instructions


class TestReadOnlyMode:
    """Remotely driven PC: observation mode must be watertight."""

    @pytest.fixture
    def readonly(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv(server.READONLY_VAR, "1")

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", "On"])
    def test_the_accepted_forms(self, monkeypatch, tmp_path, value):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv(server.READONLY_VAR, value)
        assert server._readonly() is True

    @pytest.mark.parametrize("value", ["", "0", "false", "no", "maybe"])
    def test_the_forms_that_do_not_trigger_it(self, monkeypatch, tmp_path, value):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv(server.READONLY_VAR, value)
        assert server._readonly() is False

    def test_the_message_names_the_variable_to_remove(self, readonly):
        with pytest.raises(RuntimeError) as error:
            server._guard()

        assert server.READONLY_VAR in str(error.value)
        assert "read-only" in str(error.value).lower()

    @pytest.mark.parametrize(
        "call",
        [
            pytest.param(lambda: server.mouse_move(0, 0), id="mouse_move"),
            pytest.param(lambda: server.mouse_click(), id="mouse_click"),
            pytest.param(lambda: server.mouse_drag(0, 0, 1, 1), id="mouse_drag"),
            pytest.param(lambda: server.mouse_scroll(1), id="mouse_scroll"),
            pytest.param(lambda: server.type_text("hello"), id="type_text"),
            pytest.param(lambda: server.press_key("enter"), id="press_key"),
            pytest.param(lambda: server.hotkey(["ctrl", "c"]), id="hotkey"),
            pytest.param(lambda: server.paste_text("hello"), id="paste_text"),
            pytest.param(lambda: server.clipboard("write", "hello"), id="clipboard_write"),
            pytest.param(lambda: server.launch_app("notepad"), id="launch_app"),
            pytest.param(lambda: server.run_powershell("echo hello"), id="run_powershell"),
            pytest.param(lambda: server.focus_window("x"), id="focus_window"),
            pytest.param(lambda: server.window_action("x", "minimize"), id="window_action"),
            pytest.param(lambda: server.move_window("x", 0, 0), id="move_window"),
        ],
    )
    def test_every_action_is_blocked(self, readonly, call):
        """None of these functions may touch the desktop before testing the guard."""
        with pytest.raises(RuntimeError, match=server.READONLY_VAR):
            call()

    def test_reads_remain_possible(self, readonly):
        assert server.screen_info()["readonly_mode"] is True
        assert server.list_windows()["count"] >= 1
        assert "text" in server.clipboard("read")
        assert server.notification_status()["windows_toast"] == "always available"

    def test_capture_remains_possible(self, readonly):
        result = server.screenshot(monitor=1, max_width=200)

        assert len(result) == 2
        assert "Capture" in result[1]


class TestGuidingErrors:
    def test_a_missing_window_points_at_list_windows(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        with pytest.raises(ValueError, match="list_windows"):
            server._window_or_fail("zzz-no-window-has-this-title-zzz")

    def test_an_unknown_clipboard_action_is_refused(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        with pytest.raises(ValueError, match="read or write"):
            server.clipboard("erase")


class TestSideEffectFreeTools:
    def test_wait_caps_the_requested_duration(self, tmp_path, monkeypatch):
        """A `wait(3600)` would freeze the MCP server for an hour: the cap is a safeguard."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(server.time, "sleep", lambda s: None)

        assert server.wait(9999)["waited"] == 120.0
        assert server.wait(-5)["waited"] == 0.0

    def test_screen_info_describes_the_desktop_and_the_cursor(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        info = server.screen_info()

        assert info["virtual_desktop"]["width"] > 0
        assert set(info["cursor"]) == {"x", "y"}
        assert info["dpi_awareness"] in {"per-monitor-v2", "per-monitor", "system", "none"}
        assert info["monitors"][0]["index"] == 0

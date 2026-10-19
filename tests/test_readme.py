"""The README against the code it describes.

The README is also the PyPI page: it is what a newcomer reads before trusting
this server with their desktop. When it drifts from the code, nothing breaks --
the drift is simply published. It happened once: the typing delay was fixed
from 3 ms to 15 ms in 0.1.1, and the README kept advertising the 3 ms that had
just been measured to fail.

These tests read the sources with `ast` instead of importing them: no ctypes, no
screen, so they run on any system.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
SOURCES = ROOT / "src" / "winctl"


def _is_tool_decorator(node: ast.expr) -> bool:
    """`@mcp.tool` or `@mcp.tool(...)`."""
    target = node.func if isinstance(node, ast.Call) else node
    return (
        isinstance(target, ast.Attribute)
        and target.attr == "tool"
        and isinstance(target.value, ast.Name)
        and target.value.id == "mcp"
    )


def _declared_tools() -> set[str]:
    tree = ast.parse((SOURCES / "server.py").read_text(encoding="utf-8"))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(_is_tool_decorator(d) for d in node.decorator_list)
    }


def _module_constant(module: str, name: str) -> float:
    tree = ast.parse((SOURCES / f"{module}.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == name
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in {module}.py")


def _section(title: str) -> str:
    """Body of a `## ` section, up to the next one."""
    match = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## )", README, re.M | re.S)
    assert match, f"README section not found: {title}"
    return match.group(1)


def _documented_tools() -> set[str]:
    """Names in the first column of the tables under "The tools"."""
    names: set[str] = set()
    for line in _section("The tools").splitlines():
        cells = line.split("|")
        if len(cells) > 2 and "`" in cells[1]:
            names.update(re.findall(r"`([a-z_]+)`", cells[1]))
    return names


class TestToolTables:
    def test_the_sources_declare_tools(self):
        """Guards the parser: an empty set would make the next test vacuous."""
        assert len(_declared_tools()) > 20

    def test_every_tool_is_in_a_table_and_nothing_else(self):
        assert _documented_tools() == _declared_tools()

    def test_the_layout_announces_the_right_count(self):
        count = re.search(r"definition of the (\d+) MCP tools", _section("Layout"))
        assert count, "the Layout section no longer states the tool count"
        assert int(count.group(1)) == len(_declared_tools())


class TestTypingDelay:
    def test_the_readme_states_the_delay_actually_used(self):
        stated = re.search(r"spaced\s+by\s+(\d+)\s+ms", _section("Notable implementation details"))
        assert stated, "the README no longer states the typing delay"
        assert int(stated.group(1)) == round(_module_constant("winapi", "CHAR_DELAY") * 1000)

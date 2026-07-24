"""Tests for the tool registry + adapter loader (CONTRACT §2, INV-19/22/23).

Covers the tool-spec data whitelist (`TOOLS.md`), its parser, and the
adapter-kind loader `import_tool_adapter` (mirrors `import_archetype`). No LLM,
no network — the registry is DATA and the loader is a fail-closed importlib gate.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import roles_tools as rt  # noqa: E402


_REGISTRY = """# Tools Registry

## Active Tools

| Tool ID | Direction | Adapter | Cadence Slot | Grounding Landing | Budget | Credential | MCP Binding | Act Config | Plain Purpose | Usage Note | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| notion-board | read | mcp | on-demand | ephemeral | unlimited | secret://notion | mcp__notion__query | — | Reads your Notion task board. | Call when you need the live task list. | active |
| perplexity | read | mcp | on-demand | ephemeral | 5 | secret://perplexity | mcp__perplexity__search | — | Web search. | Verify a fact against the world. | active |
| echo-http | read | http | on-demand | ephemeral | 3 | — | — | — | A plain HTTP GET. | Fetch a URL and read the body. | active |
| board-write | act | http | on-demand | round-trip | unlimited | secret://board | — | base_host=https://api.example.com;collection=issues;version_field=updated_at;match_field=title;id_field=number | Writes a task board. | Reconcile the board under a mandate. | active |
| old-tool | read | http | on-demand | ephemeral | 1 | — | — | — | Deprecated. | — | deprecated |
| unpinned-mcp | read | mcp | on-demand | ephemeral | 1 | — | — | — | An mcp tool with no binding. | Should be dropped. | active |
"""


def _write_registry(path: Path, text: str = _REGISTRY) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class RegistryParseTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        _write_registry(rt.tools_registry_path(self.base))

    def test_active_tools_parsed(self) -> None:
        reg = rt.load_tools_registry(self.base)
        # Deprecated rows excluded; an unpinned mcp row is DROPPED (INV-23 safety).
        self.assertEqual(set(reg), {"notion-board", "perplexity", "echo-http", "board-write"})

    def test_act_tool_config_parsed(self) -> None:
        spec = rt.get_tool("board-write", self.base)
        self.assertTrue(spec.is_act)
        cfg = spec.act_config_map()
        self.assertEqual(cfg["base_host"], "https://api.example.com")
        self.assertEqual(cfg["collection"], "issues")
        self.assertEqual(cfg["version_field"], "updated_at")
        self.assertEqual(cfg["match_field"], "title")
        self.assertEqual(cfg["id_field"], "number")

    def test_read_tool_has_empty_act_config(self) -> None:
        self.assertEqual(rt.get_tool("echo-http", self.base).act_config_map(), {})

    def test_mcp_binding_pinned(self) -> None:
        self.assertEqual(
            rt.get_tool("notion-board", self.base).mcp_binding, "mcp__notion__query")

    def test_http_tool_has_no_binding(self) -> None:
        self.assertIsNone(rt.get_tool("echo-http", self.base).mcp_binding)

    def test_unpinned_mcp_tool_dropped(self) -> None:
        # An mcp tool with no valid MCP Binding is unsafe (the body would choose the
        # target) → dropped from the registry, never grantable.
        self.assertIsNone(rt.get_tool("unpinned-mcp", self.base))

    def test_tool_spec_fields(self) -> None:
        spec = rt.get_tool("notion-board", self.base)
        self.assertEqual(spec.direction, "read")
        self.assertEqual(spec.adapter, "mcp")
        self.assertEqual(spec.cadence_slot, "on-demand")
        self.assertEqual(spec.grounding_landing, "ephemeral")
        self.assertIsNone(spec.max_calls_per_run)  # unlimited → None
        self.assertEqual(spec.credential_ref, "secret://notion")
        self.assertEqual(spec.on_error, "declare-unknown")  # FIXED
        self.assertTrue(spec.plain_purpose)

    def test_capped_budget_is_int(self) -> None:
        self.assertEqual(rt.get_tool("perplexity", self.base).max_calls_per_run, 5)

    def test_no_credential_is_none(self) -> None:
        self.assertIsNone(rt.get_tool("echo-http", self.base).credential_ref)

    def test_unknown_tool_is_none(self) -> None:
        self.assertIsNone(rt.get_tool("nonesuch", self.base))

    def test_missing_registry_is_empty(self) -> None:
        empty_base = Path(self._tmp.name) / "nope"
        self.assertEqual(rt.load_tools_registry(empty_base), {})

    def test_budget_unlimited_helper(self) -> None:
        self.assertTrue(rt.is_unlimited(rt.get_tool("notion-board", self.base)))
        self.assertFalse(rt.is_unlimited(rt.get_tool("perplexity", self.base)))


class BadRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)

    def test_bad_direction_row_skipped(self) -> None:
        _write_registry(rt.tools_registry_path(self.base), _REGISTRY.replace(
            "| notion-board | read |", "| notion-board | sideways |"))
        reg = rt.load_tools_registry(self.base)
        self.assertNotIn("notion-board", reg)  # invalid row dropped, others survive
        self.assertIn("perplexity", reg)

    def test_bad_adapter_row_skipped(self) -> None:
        _write_registry(rt.tools_registry_path(self.base), _REGISTRY.replace(
            "| perplexity | read | mcp |", "| perplexity | read | telepathy |"))
        reg = rt.load_tools_registry(self.base)
        self.assertNotIn("perplexity", reg)


class AdapterLoaderTest(unittest.TestCase):
    def test_unknown_adapter_kind_fail_closed(self) -> None:
        with self.assertRaises(rt.ToolAdapterError):
            rt.import_tool_adapter("nonesuch")

    def test_out_of_taxonomy_adapter_refused(self) -> None:
        # 'custom' is a conscious de-scope (INV-22) — must never load.
        with self.assertRaises(rt.ToolAdapterError):
            rt.import_tool_adapter("custom")

    def test_unsafe_adapter_name_refused(self) -> None:
        with self.assertRaises(rt.ToolAdapterError):
            rt.import_tool_adapter("../evil")

    def test_taxonomy_is_closed_and_small(self) -> None:
        self.assertEqual(
            rt.TOOL_ADAPTERS,
            frozenset({"mcp", "http", "local", "web", "skill", "subagent"}),
        )


if __name__ == "__main__":
    unittest.main()

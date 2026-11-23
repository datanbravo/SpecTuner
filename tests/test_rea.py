import asyncio
import json
import os
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from mcp.types import CallToolResult, TextContent

from spectuner.config import Registration, default_config_path, load_registration
from spectuner.rea import ReaError, check_rea, inspect_directory


DEMO = Path(__file__).resolve().parents[1] / "examples" / "inspection-demo"


STATUS = {
    "result": {
        "open": False,
        "analysis_provider_candidates": [
            {"provider": {"name": "Hopper"}, "availability": {"status": "available"}},
        ],
        "capabilities": [{"provider": {"name": ".NET static analysis"}}],
        "tool_availability": {
            "groups": [
                {"names": ["binary_session"], "available": True, "reason": "available"},
                {"names": ["open_binary"], "available": True, "reason": "available"},
                {"names": ["xrefs"], "available": False, "reason": "target_required"},
            ],
        },
    },
}


class ReaAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.registration = Registration("rea", ("mcp",), {"EXAMPLE": "value"}, Path.cwd(), 1, 1)
        self.session = SimpleNamespace(
            initialize=AsyncMock(return_value=SimpleNamespace(
                serverInfo=SimpleNamespace(name="rea", version="6.7.0"),
                protocolVersion="2025-06-18",
            )),
            list_tools=AsyncMock(side_effect=[
                SimpleNamespace(tools=[SimpleNamespace(name="open_binary")], nextCursor="next"),
                SimpleNamespace(
                    tools=[SimpleNamespace(name=name) for name in ("binary_session", "xrefs")],
                    nextCursor=None,
                ),
            ]),
            call_tool=AsyncMock(return_value=CallToolResult(content=[], structuredContent=STATUS)),
        )
        self.closed = False
        self.params = None

        @asynccontextmanager
        async def transport(params):
            self.params = params
            try:
                yield "read", "write"
            finally:
                self.closed = True

        @asynccontextmanager
        async def client(_read, _write):
            yield self.session

        self.enterContext(patch("spectuner.rea.stdio_client", transport))
        self.enterContext(patch("spectuner.rea.ClientSession", client))

    async def test_discovers_pages_and_calls_only_read_only_status(self):
        report = await check_rea(self.registration)
        self.assertEqual(report.version, "6.7.0")
        self.assertFalse(report.target_open)
        self.assertEqual(report.providers[0].status, "available")
        self.assertEqual(report.session_capabilities, (".NET static analysis",))
        self.assertEqual({item.name: item.available for item in report.tools}, {
            "binary_session": True, "open_binary": True, "xrefs": False,
        })
        self.assertEqual([call.kwargs["cursor"] for call in self.session.list_tools.await_args_list], [None, "next"])
        self.session.call_tool.assert_awaited_once_with("binary_session", arguments={})
        self.assertEqual(self.params.command, "rea")
        self.assertEqual(self.params.args, ["mcp"])
        self.assertEqual(self.params.env, {"EXAMPLE": "value"})
        self.assertTrue(self.closed)

    async def test_accepts_json_text_fallback(self):
        self.session.call_tool.return_value = CallToolResult(
            content=[TextContent(type="text", text=json.dumps(STATUS))],
        )
        self.assertFalse((await check_rea(self.registration)).target_open)

    async def test_does_not_call_missing_tool(self):
        self.session.list_tools.side_effect = None
        self.session.list_tools.return_value = SimpleNamespace(tools=[], nextCursor=None)
        with self.assertRaisesRegex(ReaError, "did not advertise"):
            await check_rea(self.registration)
        self.session.call_tool.assert_not_awaited()
        self.assertTrue(self.closed)

    async def test_reports_tool_error(self):
        self.session.call_tool.return_value = CallToolResult(
            isError=True, content=[TextContent(type="text", text="unavailable")],
        )
        with self.assertRaisesRegex(ReaError, "returned an error"):
            await check_rea(self.registration)
        self.assertTrue(self.closed)

    async def test_inspects_only_explicit_directory_and_requests_summary(self):
        operation = "analyze_javascript_application"
        self.session.list_tools.side_effect = None
        self.session.list_tools.return_value = SimpleNamespace(
            tools=[SimpleNamespace(name=operation)], nextCursor=None,
        )
        evidence = {"normalized_result": {"kind": "summary"}}
        self.session.call_tool.return_value = CallToolResult(content=[], structuredContent=evidence)
        self.assertEqual(await inspect_directory(self.registration, DEMO), evidence)
        self.session.call_tool.assert_awaited_once_with(operation, arguments={
            "input_path": str(DEMO), "format": "directory", "detail": "summary",
        })
        self.assertTrue(self.closed)

    async def test_rejects_file_instead_of_directory_before_connecting(self):
        with self.assertRaisesRegex(ReaError, "Expected a local JavaScript application directory"):
            await inspect_directory(self.registration, DEMO / "main.js")
        self.session.initialize.assert_not_awaited()

    async def test_times_out_during_initialization(self):
        async def slow_initialize():
            await asyncio.sleep(10)

        self.session.initialize.side_effect = slow_initialize
        short = Registration("rea", (), {}, None, 0.01, 1)
        with self.assertRaisesRegex(ReaError, "Timed out initializing"):
            await check_rea(short)
        self.assertTrue(self.closed)


@unittest.skipUnless(os.environ.get("SPECTUNER_TEST_LIVE_REA") == "1", "opt-in live REA connection")
class LiveReaTest(unittest.IsolatedAsyncioTestCase):
    async def test_read_only_connection(self):
        report = await check_rea(load_registration(default_config_path()))
        self.assertEqual(report.server, "rea")
        self.assertFalse(report.target_open)
        self.assertIn("binary_session", {tool.name for tool in report.tools if tool.available})

    async def test_inspects_first_party_demo(self):
        evidence = await inspect_directory(load_registration(default_config_path()), DEMO)
        result = evidence["normalized_result"]
        self.assertEqual(result["parent_operation"], "analyze_javascript_application")
        self.assertEqual(result["summary"]["input_path"], str(DEMO))
        self.assertEqual(result["summary"]["format"], "directory")
        self.assertTrue(result["summary"]["root_artifact_sha256"])

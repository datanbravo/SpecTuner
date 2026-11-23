import asyncio
import io
import json
import os
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, Mock, patch

from spectuner.cli import main
from spectuner.config import Registration
from spectuner.model import CodexProvider, ModelError
from spectuner.planner import SOURCE_FILE, PlanningError, PlanningInputs, plan_optimization
from spectuner.unity import CAPTURE_HEADER, WORKLOAD_TYPE


MVID = "55856bd0-027a-4366-94e4-098b17038f53"
PROPOSAL = {
    "source_file": SOURCE_FILE.as_posix(),
    "method": "FindClosestWaypoint",
    "rea_fact_ids": ["R1"],
    "benchmark_fact_ids": ["B2"],
    "proposed_modification": "Evaluate caching waypoint indices with explicit position validity rules.",
    "expected_benefit": "Might reduce repeated searches when positions are identical.",
    "risks": ["Incorrect cache invalidation can change waypoint selection."],
    "validation_plan": ["Check identical decisions and run repeated paired captures."],
}


def managed_evidence(mvid=MVID):
    return {
        "evidence_id": "ev_test",
        "provider": {"id": "rea-dotnet-static"},
        "normalized_result": {
            "module": {"mvid": mvid},
            "selection": {"type_names": [WORKLOAD_TYPE], "unmatched_type_names": []},
            "coverage": {"state": "complete"},
            "artifact": {"sha256": "a" * 64},
            "methods": [{
                "name": "FindClosestWaypoint", "token": "0x06000001",
                "body": {"status": "present", "il_sha256": "b" * 64, "opcode_counts": {}},
            }],
            "call_edges": [{
                "caller_token": "0x06000001", "target_declaring_type": "UnityEngine.Vector3",
                "target_name": "Distance",
            }],
        },
    }


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.project = Path(self.enterContext(TemporaryDirectory()))
        source = self.project / SOURCE_FILE
        source.parent.mkdir(parents=True)
        source.write_text("private static int FindClosestWaypoint() { return 0; }", encoding="utf-8")
        self.baseline, self.optimized = self.project / "before.csv", self.project / "after.csv"
        for path, mode, small_frame_time in (
            (self.baseline, "baseline", 100), (self.optimized, "optimized", 10),
        ):
            path.write_text(
                ",".join(CAPTURE_HEADER) + "\n"
                + f"npc-scan,64,0,{small_frame_time},{1000 / small_frame_time},1,editor,{MVID},{mode},512\n"
                + f"npc-scan,1024,0,10,100,2,editor,{MVID},{mode},1024\n",
                encoding="utf-8",
            )
        self.assembly = self.project / "sample.dll"
        self.inputs = PlanningInputs(self.project, self.assembly, self.baseline, self.optimized)
        self.registration = Registration("rea", (), {}, None, 1, 1)
        self.provider = Mock(name="mock provider")
        self.provider.name = "mock"
        self.provider.generate.return_value = PROPOSAL.copy()
        self.inspect = self.enterContext(patch(
            "spectuner.planner.inspect_unity_assembly", new_callable=AsyncMock,
            return_value=managed_evidence(),
        ))

    def test_builds_grounded_report_and_sets_approval_pending(self):
        report = asyncio.run(plan_optimization(self.registration, self.inputs, self.provider))
        self.inspect.assert_awaited_once_with(self.registration, self.assembly, complete=True)
        self.assertEqual(report["provider"], "mock")
        self.assertEqual(report["approval"], {"status": "pending", "required_before_changes": True})
        evidence = report["evidence"]
        self.assertEqual(evidence["benchmarks"]["facts"]["B1"]["comparable_window"], False)
        self.assertEqual(evidence["benchmarks"]["facts"]["B2"]["comparable_window"], True)
        self.assertEqual(evidence["benchmarks"]["captures"]["baseline"]["filename"], self.baseline.name)
        self.assertEqual(evidence["rea"]["facts"]["R1"]["static_calls"], ["UnityEngine.Vector3.Distance"])
        prompt, schema = self.provider.generate.call_args.args
        self.assertIn("private static int FindClosestWaypoint", prompt)
        self.assertNotIn(str(self.project), prompt)
        self.assertEqual(set(schema["required"]), set(PROPOSAL))

    def test_aborts_on_cil_mvid_mismatch_before_model_call(self):
        self.inspect.return_value = managed_evidence("a593c172-1472-4436-8ea3-22ac942ea5d5")
        with self.assertRaisesRegex(PlanningError, "MVID does not match"):
            asyncio.run(plan_optimization(self.registration, self.inputs, self.provider))
        self.provider.generate.assert_not_called()

    def test_rejects_unscoped_or_unsubstantiated_model_output(self):
        cases = [
            ({"source_file": "Elsewhere.cs"}, "outside the inspected scope"),
            ({"method": "Unknown"}, "must have a cited REA finding"),
            ({"rea_fact_ids": ["R99"]}, "unknown REA fact"),
            ({"benchmark_fact_ids": ["B999"]}, "unknown benchmark fact"),
            ({"benchmark_fact_ids": ["B1"]}, "at least one comparable benchmark"),
            ({"risks": []}, "nonempty list of risks"),
            ({"approval": "approved"}, "do not match"),
        ]
        for changes, message in cases:
            with self.subTest(changes=changes), self.assertRaisesRegex(PlanningError, message):
                self.provider.generate.return_value = PROPOSAL | changes
                asyncio.run(plan_optimization(self.registration, self.inputs, self.provider))

    def test_cli_writes_once_and_protects_unity_directory(self):
        config_path = self.project / "config.toml"
        config_path.write_text('[mcp_servers.rea]\ncommand="rea"\n', encoding="utf-8")
        command = [
            "--config", str(config_path), "plan", "--project-root", str(self.project),
            "--assembly", str(self.assembly), "--baseline", str(self.baseline),
            "--optimized", str(self.optimized), "--output",
        ]
        output = self.project / "proposal.json"
        with patch("spectuner.model.CodexProvider.generate", return_value=PROPOSAL) as model:
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(main([*command, str(output)]), 0)
                self.assertEqual(main([*command, str(output)]), 1)
                self.assertEqual(main([*command, str(self.project / "unity" / "invalid.json")]), 1)
        model.assert_called_once()
        self.assertEqual(json.loads(output.read_text())["proposal"], PROPOSAL)


class CodexProviderTests(unittest.TestCase):
    @patch("spectuner.model.shutil.which", return_value="/usr/bin/codex")
    @patch("spectuner.model.subprocess.run")
    def test_runs_authenticated_cli_without_tools_or_api_keys(self, run, _which):
        def respond(args, **kwargs):
            self.assertIn("read-only", args)
            self.assertIn("--ignore-user-config", args)
            self.assertIn("--ephemeral", args)
            self.assertIn("shell_tool", args)
            self.assertNotIn("OPENAI_API_KEY", kwargs["env"])
            self.assertNotIn("CODEX_API_KEY", kwargs["env"])
            self.assertEqual(kwargs["env"]["CODEX_HOME"], "/test/codex-home")
            self.assertEqual(kwargs["input"], "private planning input")
            schema = Path(args[args.index("--output-schema") + 1])
            self.assertEqual(json.loads(schema.read_text()), {"type": "object"})
            output = Path(args[args.index("--output-last-message") + 1])
            output.write_text('{"proposal":"example"}')
            return subprocess.CompletedProcess(args, 0, "", "")

        run.side_effect = respond
        with patch.dict(os.environ, {
            "OPENAI_API_KEY": "mock-key", "CODEX_API_KEY": "mock-key", "CODEX_HOME": "/test/codex-home",
        }):
            provider = CodexProvider(model="configured-model")
            self.assertEqual(provider.generate("private planning input", {"type": "object"}), {"proposal": "example"})
        self.assertIn("configured-model", run.call_args.args[0])

    @patch("spectuner.model.shutil.which", return_value="/usr/bin/codex")
    @patch("spectuner.model.subprocess.run")
    def test_model_failures_do_not_leak_provider_stderr(self, run, _which):
        run.return_value = subprocess.CompletedProcess([], 1, "", "sensitive provider stderr")
        with self.assertRaisesRegex(ModelError, "Check codex login status") as raised:
            CodexProvider().generate("evidence", {})
        self.assertNotIn("sensitive", str(raised.exception))
        run.side_effect = subprocess.TimeoutExpired([], 1)
        with self.assertRaisesRegex(ModelError, "timed out"):
            CodexProvider(timeout=1).generate("evidence", {})

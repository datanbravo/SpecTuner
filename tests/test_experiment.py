import asyncio
import csv
import hashlib
import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, Mock, patch

from spectuner.config import Registration
from spectuner.experiment import (
    DLL, PROJECT_FILES, UNITY_CHECKS, WORKLOAD, ExperimentError, finish_experiment,
    prepare_experiment, run_experiment, run_unity_checks,
)
from spectuner.experiment_metrics import evaluate_captures
from spectuner.planner import SOURCE_FILE, PlanningInputs
from spectuner.unity import CAPTURE_HEADER


ROOT = Path(__file__).resolve().parents[1]
BASELINE_MVID = "55856bd0-027a-4366-94e4-098b17038f53"
CANDIDATE_MVID = "1a993903-5566-4ee4-a5ba-69cf15eab553"
RECIPE = {"operation": "hoist_movement_step", "local_name": "movementStep"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def captures(directory, changes, *, regression=False):
    baselines, candidates = [], []
    for trial, reduction in enumerate(changes):
        for name, mvid, paths in (
            ("baseline", BASELINE_MVID, baselines), ("candidate", CANDIDATE_MVID, candidates),
        ):
            path = directory / f"{name}-{trial}.csv"
            paths.append(path)
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(CAPTURE_HEADER)
                for count in (64, 256, 1024):
                    frame_ms = 100 if name == "baseline" or count != 64 or not regression else 104
                    workload = 10 if name == "baseline" or count != 1024 else 10 * (1 - reduction)
                    for index in range(100):
                        writer.writerow([
                            "npc-scan", count, index, frame_ms, 1000 / frame_ms, workload,
                            "editor", mvid, "optimized", 1024 + trial,
                        ])
    return baselines, candidates


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = Path(self.enterContext(TemporaryDirectory())).resolve()
        project = self.temporary / "original"
        self.original = project / SOURCE_FILE
        for relative in PROJECT_FILES:
            destination = project / "unity" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((ROOT / "unity" / relative).read_bytes())
        self.original_bytes = self.original.read_bytes()
        self.workspace = self.temporary / "experiment"
        self.editor = self.temporary / "Unity"
        self.editor.touch()
        assembly, baseline, optimized = (
            self.temporary / "source.dll", self.temporary / "prior-baseline.csv", self.temporary / "prior-opt.csv",
        )
        for path in (assembly, baseline, optimized):
            path.write_text(path.name)
        self.inputs = PlanningInputs(project, assembly, baseline, optimized)
        self.evidence = {
            "source": {"path": SOURCE_FILE.as_posix(), "sha256": digest(self.original_bytes)},
            "rea": {"artifact_sha256": digest(assembly.read_bytes()), "facts": {"R1": {"method": "Tick"}}},
            "benchmarks": {
                "facts": {"B1": {"comparable_window": True}},
                "captures": {key: {"sha256": digest(path.read_bytes())} for key, path in (
                    ("baseline", baseline), ("optimized", optimized),
                )},
            },
        }
        self.plan = self.temporary / "planner-report.json"
        self.plan.write_text(json.dumps({
            "report_version": 1, "approval": {"status": "pending", "required_before_changes": True},
            "evidence": self.evidence,
            "proposal": {
                "source_file": SOURCE_FILE.as_posix(), "method": "Tick", "rea_fact_ids": ["R1"],
                "benchmark_fact_ids": ["B1"], "proposed_modification": "Hoist deltaSeconds * 2f.",
                "expected_benefit": "One multiply per tick.", "risks": ["No measurable gain."],
                "validation_plan": ["Compare decisions and paired captures."],
            },
        }))
        self.registration = Registration("rea", (), {}, None, 1, 1)
        self.model = Mock()
        self.model.name = "test-model"
        self.model.generate.return_value = RECIPE.copy()
        self.gather = self.enterContext(patch(
            "spectuner.experiment.gather_evidence", new_callable=AsyncMock,
            return_value=(self.evidence, self.original_bytes.decode()),
        ))

    def prepare(self):
        return asyncio.run(prepare_experiment(
            self.registration, self.inputs, self.plan, self.workspace, self.model,
        ))["review_id"]

    def run_review(self, review_id):
        return asyncio.run(run_experiment(
            self.registration, self.workspace, review_id, "Reviewer", self.editor, 30,
        ))

    def mock_builds(self, candidate_status="passed"):
        def checks(editor, project, log, timeout):
            variant = project.name
            dll = project / DLL
            dll.parent.mkdir(parents=True)
            dll.write_bytes(variant.encode())
            status = candidate_status if variant == "candidate" else "passed"
            return {"status": status, "reason": "synthetic test result"}

        async def inspect(registration, project):
            return {
                "mvid": BASELINE_MVID if project.name == "baseline" else CANDIDATE_MVID,
                "sha256": digest((project / DLL).read_bytes()),
            }

        self.enterContext(patch("spectuner.experiment.run_unity_checks", side_effect=checks))
        self.enterContext(patch("spectuner.experiment._inspect_build", side_effect=inspect))

    def test_preparation_verifies_evidence_and_waits_for_exact_approval(self):
        review_id = self.prepare()
        delta = (self.workspace / "candidate.diff").read_text()
        self.assertIn("+            float movementStep = deltaSeconds * 2f;", delta)
        self.assertTrue(review_id)
        self.assertFalse((self.workspace / "candidate").exists())
        with self.assertRaisesRegex(ExperimentError, "exact review ID"):
            self.run_review("unapproved")
        self.assertFalse((self.workspace / "report.json").exists())
        self.assertEqual(self.original.read_bytes(), self.original_bytes)

    def test_stale_evidence_stops_before_model_or_workspace_creation(self):
        stale = self.evidence | {"source": {}}
        self.gather.return_value = stale, self.original_bytes.decode()
        with self.assertRaisesRegex(ExperimentError, "evidence is stale"):
            self.prepare()
        self.model.generate.assert_not_called()
        self.assertFalse(self.workspace.exists())

    def test_unsupported_model_recipe_cannot_supply_code_or_commands(self):
        self.model.generate.return_value = RECIPE | {"local_name": "movementStep; run command"}
        with self.assertRaisesRegex(ExperimentError, "unsupported edit recipe"):
            self.prepare()
        self.assertFalse(self.workspace.exists())

    def test_tampered_patch_and_inputs_are_refused(self):
        review_id = self.prepare()
        patch_path = self.workspace / "candidate.diff"
        original = patch_path.read_bytes()
        patch_path.write_bytes(b"changed")
        with self.assertRaisesRegex(ExperimentError, "patch file changed"):
            self.run_review(review_id)
        patch_path.write_bytes(original)
        self.inputs.assembly.write_bytes(b"changed")
        with self.assertRaisesRegex(ExperimentError, "assembly input changed"):
            self.run_review(review_id)
        self.assertFalse((self.workspace / "candidate").exists())

    def test_failure_restores_candidate_and_incomplete_tests_are_inconclusive(self):
        for status, decision in (("failed", "rejected"), ("inconclusive", "inconclusive")):
            with self.subTest(status=status):
                self.workspace = self.temporary / status
                self.mock_builds(status)
                report = self.run_review(self.prepare())
                self.assertEqual(report["decision"], decision)
                self.assertTrue(report["restored"])
                self.assertEqual((self.workspace / "candidate" / WORKLOAD).read_bytes(), self.original_bytes)
        self.assertEqual(self.original.read_bytes(), self.original_bytes)

    def test_passed_tests_wait_for_captures_and_rejection_restores_only_candidate(self):
        self.mock_builds()
        report = self.run_review(self.prepare())
        self.assertEqual(report["state"], "awaiting_captures")
        self.assertNotEqual((self.workspace / "candidate" / WORKLOAD).read_bytes(), self.original_bytes)
        self.assertEqual((self.workspace / "baseline" / WORKLOAD).read_bytes(), self.original_bytes)
        self.assertEqual(finish_experiment(self.workspace, [], [])["decision"], "inconclusive")
        baselines, candidates = captures(self.temporary, [0.01] * 5)
        report = finish_experiment(self.workspace, baselines, candidates)
        self.assertEqual(report["decision"], "rejected")
        self.assertTrue(report["restored"])
        self.assertEqual((self.workspace / "candidate" / WORKLOAD).read_bytes(), self.original_bytes)
        self.assertEqual(self.original.read_bytes(), self.original_bytes)

    def test_reviewed_candidate_with_matching_evidence_can_pass(self):
        self.mock_builds()
        self.run_review(self.prepare())
        baselines, candidates = captures(self.temporary, [0.10] * 5)
        report = finish_experiment(self.workspace, baselines, candidates)
        self.assertEqual(report["decision"], "accepted")
        self.assertFalse(report["restored"])
        self.assertEqual(len(report["measurements"]["pairs"]), 5)

    def test_unity_uses_fixed_checks_and_requires_all_markers(self):
        project = self.temporary / "test-project"
        dll = project / DLL
        dll.parent.mkdir(parents=True)
        dll.touch()
        log = self.temporary / "compile.log"
        log.write_text(UNITY_CHECKS[0])
        with patch("spectuner.experiment.subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as command:
            result = run_unity_checks(self.editor, project, log, 30)
            self.assertEqual(result["status"], "inconclusive")
            self.assertIn("SpecTuner.UnityDemo.WaypointChecks.RunBatch", command.call_args.args[0])
            log.write_text("\n".join(UNITY_CHECKS))
            self.assertEqual(run_unity_checks(self.editor, project, log, 30)["status"], "passed")


class ExperimentMetricTests(unittest.TestCase):
    def test_mixed_workload_results_and_regressions_are_distinguished(self):
        with TemporaryDirectory() as directory:
            mvids = {"baseline": BASELINE_MVID, "candidate": CANDIDATE_MVID}
            baselines, candidates = captures(Path(directory), [0.10, 0.10, 0.10, 0.01, 0.01])
            self.assertEqual(evaluate_captures(baselines, candidates, mvids)["decision"], "inconclusive")
            baselines, candidates = captures(Path(directory), [0.10] * 5, regression=True)
            self.assertEqual(evaluate_captures(baselines, candidates, mvids)["decision"], "rejected")
            result = evaluate_captures([baselines[0]] * 5, candidates, mvids)
            self.assertEqual(result["decision"], "inconclusive")
            self.assertIn("repeated capture", result["reason"])

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from spectuner.cli import main
from spectuner.unity import CAPTURE_HEADER, MEMBER_OPERATION, WORKLOAD_TYPE, baseline_report, read_capture, read_rea_finding


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples" / "unity-synthetic.csv"
MVID = "72848892-07ff-4f2a-8d19-8023d106b968"


class UnityCaptureTests(unittest.TestCase):
    def test_baseline_cli_reports_measurements_and_source_hypotheses(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["baseline", str(FIXTURE)]), 0)
        report = output.getvalue()
        self.assertIn("| npc-scan | 1024 | 2 | 44.44 | 22.50 | 25.00 | 2/2 (100.0%) | 9.200 |", report)
        self.assertIn("P95 exceeds the frame budget for npc-scan at 1024 NPCs.", report)
        self.assertIn("No REA evidence supplied.", report)
        self.assertIn("Source hypothesis from NpcWorkload.MeasureWaypoints", report)
        self.assertIn("No optimization was applied or measured.", report)

    def test_rejects_inconsistent_capture_data(self):
        row = f"npc-scan,64,0,10,100,0,editor,{MVID}\n"
        cases = (
            (row.replace(",100,", ",90,"), "FPS inconsistent"),
            (row.replace(",0,10,", ",1,10,"), "frame_index must be consecutive"),
            (row.replace(",10,", ",NaN,"), "invalid timings"),
            (row + row.replace(",editor,", ",player,"), "mixed run modes"),
            (row + row.replace(MVID, "130462e6-ae07-4be3-9120-e76c41dbacf1"), "assembly MVIDs"),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.csv"
            for csv_rows, error in cases:
                with self.subTest(error=error):
                    path.write_text(",".join(CAPTURE_HEADER) + "\n" + csv_rows, encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, error):
                        read_capture(path)

    def test_export_header_matches_python_reader(self):
        source = (ROOT / "unity" / "Assets" / "Runtime" / "BenchmarkRunner.cs").read_text(encoding="utf-8")
        self.assertIn(f'writer.WriteLine("{",".join(CAPTURE_HEADER)}")', source)

    def test_rejects_invalid_frame_rate_budget(self):
        for target in (0, -1, float("nan"), float("inf")):
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, "frame budget"):
                baseline_report(read_capture(FIXTURE), target)

    def test_reports_rea_evidence_with_match_and_mismatch(self):
        evidence = {"normalized_result": {
            "kind": "summary",
            "parent_operation": MEMBER_OPERATION,
            "parent_evidence_id": "ev_test",
            "summary": {
                "selection": {"type_names": [WORKLOAD_TYPE], "unmatched_type_names": []},
                "artifact": {"sha256": "a" * 64},
                "module": {"mvid": MVID},
                "coverage": {"state": "partial"},
                "reported_counts": {"methods": 3, "call_edges": 4},
            },
        }}
        capture = read_capture(FIXTURE)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rea.json"
            path.write_text(json.dumps(evidence), encoding="utf-8")
            report = baseline_report(capture, 60, read_rea_finding(path))
            self.assertIn("Module MVID agrees", report)
            self.assertIn("3 methods and 4 static call edges. Coverage partial.", report)
            evidence["normalized_result"]["summary"]["module"]["mvid"] = None
            path.write_text(json.dumps(evidence), encoding="utf-8")
            self.assertIn("Keep these findings separate", baseline_report(capture, 60, read_rea_finding(path)))
            evidence["normalized_result"]["parent_operation"] = "analyze_javascript_application"
            path.write_text(json.dumps(evidence), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "expected an inspect-unity"):
                read_rea_finding(path)

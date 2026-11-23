import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path

from spectuner.cli import main
from spectuner.unity import (
    CAPTURE_HEADER, LEGACY_CAPTURE_HEADER, MEMBER_OPERATION, WORKLOAD_TYPE,
    Frame, baseline_report, compare_unity_report, read_capture, read_rea_finding,
)


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
                    path.write_text(",".join(LEGACY_CAPTURE_HEADER) + "\n" + csv_rows, encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, error):
                        read_capture(path)

    def test_export_header_matches_python_reader(self):
        source = (ROOT / "unity" / "Assets" / "Runtime" / "BenchmarkRunner.cs").read_text(encoding="utf-8")
        self.assertIn(f'writer.WriteLine("{",".join(CAPTURE_HEADER)}")', source)

    def test_rejects_invalid_frame_rate_budget(self):
        for target in (0, -1, float("nan"), float("inf")):
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, "frame budget"):
                baseline_report(read_capture(FIXTURE), target)

    def test_slow_interval_changes_throughput_but_not_p95(self):
        frames = [Frame(4, 2)] * 100
        frames[21] = Frame(8000, 2.4)
        capture = replace(read_capture(FIXTURE), groups={("npc-scan", 1024): frames})
        report = baseline_report(capture, 60)
        self.assertIn("| npc-scan | 1024 | 100 | 11.91 | 4.00 | 4.00 | 1/100 (1.0%) | 2.000 |", report)
        self.assertIn("P99 4.00 ms, max 8000.00 ms, total 8.396 s", report)
        self.assertIn("95.3% of captured time", report)
        self.assertIn("Frame 21: 8000.00 ms interval, 2.400 ms NPC work.", report)

    def test_compare_tagged_captures_from_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            before_path = Path(directory) / "baseline.csv"
            after_path = Path(directory) / "optimized.csv"
            header = ",".join(CAPTURE_HEADER) + "\n"
            before_path.write_text(header + f"npc-scan,64,0,10,100,4,editor,{MVID},baseline,512\n"
                                   + f"npc-scan,64,1,20,50,8,editor,{MVID},baseline,768\n", encoding="utf-8")
            after_path.write_text(header + f"npc-scan,64,0,8,125,2,editor,{MVID},optimized,0\n"
                                  + f"npc-scan,64,1,10,100,4,editor,{MVID},optimized,0\n", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["compare-unity", str(before_path), str(after_path)]), 0)
            report = output.getvalue()
            self.assertIn("| P50 Frame time (ms) | 15.000 | 9.000 | -6.000 | -40.00% |", report)
            self.assertIn("| P95 Frame time (ms) | 20.000 | 10.000 | -10.000 | -50.00% |", report)
            self.assertIn("| P50 NPC workload (ms) | 6.000 | 3.000 | -3.000 | -50.00% |", report)
            self.assertIn("| P95 Managed bytes/frame | 768.000 | 0.000 | -768.000 | -100.00% |", report)

    def test_compare_reports_unavailable_allocation_and_zero_baseline(self):
        legacy = read_capture(FIXTURE)
        before = replace(legacy, optimization_mode="baseline", groups={("npc-scan", 64): [Frame(10, 0, 0)]})
        after = replace(before, optimization_mode="optimized", groups={("npc-scan", 64): [Frame(10, 1)]})
        report = compare_unity_report(before, after)
        self.assertIn("| P50 Managed bytes/frame | 0.000 | unavailable | — | — |", report)
        self.assertIn("| P50 NPC workload (ms) | 0.000 | 1.000 | +1.000 | — |", report)

    def test_compare_rejects_unmatched_captures(self):
        legacy = read_capture(FIXTURE)
        before = replace(legacy, optimization_mode="baseline")
        after = replace(legacy, optimization_mode="optimized")
        for first, second, error in (
            (legacy, after, "tagged baseline"),
            (after, before, "tagged baseline"),
            (before, replace(after, mode="player"), "same run mode and assembly MVID"),
            (before, replace(after, mvid=after.mvid.__class__(int=1)), "same run mode and assembly MVID"),
            (before, replace(after, groups={}), "same scenarios and NPC counts"),
        ):
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                compare_unity_report(first, second)

    def test_rejects_invalid_mode_and_mixed_allocation_data(self):
        row = f"npc-scan,64,0,10,100,1,editor,{MVID}"
        next_row = row.replace(",0,10,", ",1,10,")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.csv"
            for rows, error in (
                (row + ",other,1", "optimization_mode"),
                (row + ",baseline,-1", "must be nonnegative"),
                (row + ",baseline,0\n" + next_row + ",baseline,", "mixed optimization modes or allocation"),
                (row + ",baseline,0\n" + next_row + ",optimized,0", "mixed optimization modes or allocation"),
            ):
                with self.subTest(error=error):
                    path.write_text(",".join(CAPTURE_HEADER) + "\n" + rows + "\n", encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, error):
                        read_capture(path)

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

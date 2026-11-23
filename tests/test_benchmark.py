import tempfile
import unittest
from pathlib import Path

from spectuner.benchmark import compare, format_report, read_benchmark


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


class BenchmarkTests(unittest.TestCase):
    def test_sample_report(self):
        results = compare(read_benchmark(EXAMPLES / "before.csv"), read_benchmark(EXAMPLES / "after.csv"))
        arena, menu = results
        self.assertEqual(arena.scenario, "arena")
        self.assertEqual(arena.before.frames, 5)
        self.assertEqual((arena.before.median_ms, arena.after.median_ms), (22, 18))
        self.assertEqual((arena.before.p95_ms, arena.after.p95_ms), (35, 24))
        self.assertEqual(menu.changes(), (0, 0))
        self.assertIn("-18.18%", format_report(results))

    def test_rejects_invalid_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.csv"
            for data in ("", "scenario,frame_ms\n", "duration\n1\n", "scenario,frame_ms\n,1\n",
                         "scenario,frame_ms\narena,NaN\n", "scenario,frame_ms\narena,0\n"):
                with self.subTest(data=data):
                    path.write_text(data, encoding="utf-8")
                    with self.assertRaises(ValueError):
                        read_benchmark(path)

    def test_rejects_unmatched_scenarios(self):
        before = read_benchmark(EXAMPLES / "before.csv")
        with self.assertRaisesRegex(ValueError, "Scenario sets differ"):
            compare(before, {"arena": before["arena"]})

import csv
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import median


@dataclass(frozen=True)
class FrameStats:
    frames: int
    median_ms: float
    p95_ms: float


@dataclass(frozen=True)
class Comparison:
    scenario: str
    before: FrameStats
    after: FrameStats

    def changes(self) -> tuple[float, float]:
        return (
            (self.after.median_ms - self.before.median_ms) / self.before.median_ms * 100,
            (self.after.p95_ms - self.before.p95_ms) / self.before.p95_ms * 100,
        )


def read_benchmark(path: Path) -> dict[str, FrameStats]:
    samples: dict[str, list[float]] = defaultdict(list)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = csv.reader(stream, strict=True)
        if next(rows, None) != ["scenario", "frame_ms"]:
            raise ValueError(f"{path}: expected CSV header scenario,frame_ms")
        for row in rows:
            if not row:
                continue
            if len(row) != 2 or not row[0].strip():
                raise ValueError(f"{path}:{rows.line_num}: expected a scenario and frame_ms")
            try:
                duration = float(row[1])
                if not math.isfinite(duration) or duration <= 0:
                    raise ValueError
            except ValueError as error:
                raise ValueError(f"{path}:{rows.line_num}: frame_ms must be positive and finite") from error
            samples[row[0].strip()].append(duration)
    if not samples:
        raise ValueError(f"{path}: expected at least one frame")
    return {
        scenario: FrameStats(len(values), median(values), sorted(values)[math.ceil(0.95 * len(values)) - 1])
        for scenario, values in samples.items()
    }


def compare(before: dict[str, FrameStats], after: dict[str, FrameStats]) -> tuple[Comparison, ...]:
    if before.keys() != after.keys():
        raise ValueError(
            f"Scenario sets differ. Before only {sorted(before.keys() - after.keys())}. "
            f"After only {sorted(after.keys() - before.keys())}."
        )
    return tuple(Comparison(scenario, before[scenario], after[scenario]) for scenario in sorted(before))


def format_report(results: tuple[Comparison, ...]) -> str:
    lines = ["Frame times in ms. Negative change means faster."]
    for result in results:
        before, after = result.before, result.after
        median_change, p95_change = result.changes()
        lines.extend((
            f"{result.scenario} ({before.frames} → {after.frames} frames)",
            f"  Median  {before.median_ms:.3f} → {after.median_ms:.3f} ms ({median_change:+.2f}%)",
            f"  P95     {before.p95_ms:.3f} → {after.p95_ms:.3f} ms ({p95_change:+.2f}%)",
        ))
    return "\n".join(lines)

import math
from pathlib import Path
from statistics import median
from typing import Any

from .planner import read_capture_provenance, summarize_frames


POLICY = {
    "minimum_pairs": 5,
    "minimum_frames_per_group": 100,
    "capture_window_seconds": [8, 13],
    "maximum_pair_duration_ratio": 1.25,
    "npc_counts": [64, 256, 1024],
    "target_npc_count": 1024,
    "minimum_p95_workload_reduction_pct": 5,
    "maximum_median_paired_regression_pct": 2,
    "required_fraction_of_pairs_meeting_target": 0.8,
    "maximum_median_paired_allocation_increase_bytes": 0,
}
TIMING_METRICS = ("frame_p50_ms", "frame_p95_ms", "workload_p50_ms", "workload_p95_ms")
ALLOCATION = "allocation_p95_bytes_per_frame"


def _read_pair(
    baseline: Path, candidate: Path, mvids: dict[str, str], fingerprints: set[str],
) -> dict[str, Any]:
    report = {}
    for variant, path in (("baseline", baseline), ("candidate", candidate)):
        capture, origin = read_capture_provenance(path)
        if (capture.mode, capture.optimization_mode, str(capture.mvid)) != ("editor", "optimized", mvids[variant]):
            raise ValueError(f"{path.name}: wrong build MVID or run mode; use Editor/Optimized in each copy")
        if origin["sha256"] in fingerprints:
            raise ValueError(f"{path.name}: repeated capture")
        fingerprints.add(origin["sha256"])
        if set(capture.groups) != {("npc-scan", count) for count in POLICY["npc_counts"]}:
            raise ValueError(f"{path.name}: capture must contain all three demo populations")
        groups = {}
        for (_, count), frames in sorted(capture.groups.items()):
            stats = summarize_frames(frames)
            start, end = POLICY["capture_window_seconds"]
            if stats["frames"] < POLICY["minimum_frames_per_group"] or not start <= stats["duration_s"] <= end:
                raise ValueError(f"{path.name}: insufficient frames or unsuitable capture window at {count} NPCs")
            if stats[ALLOCATION] is None or any(stats[metric] <= 0 for metric in TIMING_METRICS):
                raise ValueError(f"{path.name}: missing allocation or unusable timing measurements at {count} NPCs")
            groups[str(count)] = stats
        report[variant] = {"capture": origin, "groups": groups}
    deltas = {}
    for count, before in report["baseline"]["groups"].items():
        after = report["candidate"]["groups"][count]
        windows = before["duration_s"], after["duration_s"]
        if max(windows) / min(windows) > POLICY["maximum_pair_duration_ratio"]:
            raise ValueError(f"Paired durations differ too much at {count} NPCs")
        deltas[count] = {
            **{metric: (after[metric] / before[metric] - 1) * 100 for metric in TIMING_METRICS},
            ALLOCATION: after[ALLOCATION] - before[ALLOCATION],
        }
    return {**report, "deltas": deltas}


def evaluate_captures(baselines: list[Path], candidates: list[Path], mvids: dict[str, str]) -> dict[str, Any]:
    if len(baselines) != len(candidates) or len(baselines) < POLICY["minimum_pairs"]:
        return {
            "decision": "inconclusive",
            "reason": "Provide at least five matched pairs (one unique capture per build per pair).",
            "pairs": [],
        }
    pairs = []
    fingerprints: set[str] = set()
    try:
        for baseline, candidate in zip(baselines, candidates, strict=True):
            pairs.append(_read_pair(baseline, candidate, mvids, fingerprints))
    except (OSError, ValueError) as error:
        return {"decision": "inconclusive", "reason": str(error), "pairs": pairs}

    target = str(POLICY["target_npc_count"])
    metric = "workload_p95_ms"
    threshold = -POLICY["minimum_p95_workload_reduction_pct"]
    target_passes = sum(pair["deltas"][target][metric] <= threshold for pair in pairs)
    medians = {
        str(count): {
            key: median(pair["deltas"][str(count)][key] for pair in pairs)
            for key in (*TIMING_METRICS, ALLOCATION)
        }
        for count in POLICY["npc_counts"]
    }
    regressions = [
        f"{count} NPCs, {key}" for count, deltas in medians.items() for key in TIMING_METRICS
        if deltas[key] > POLICY["maximum_median_paired_regression_pct"]
    ]
    regressions.extend(
        f"{count} NPCs, managed allocation" for count, deltas in medians.items()
        if deltas[ALLOCATION] > POLICY["maximum_median_paired_allocation_increase_bytes"]
    )
    consistent_count = math.ceil(len(pairs) * POLICY["required_fraction_of_pairs_meeting_target"])
    target_failures = sum(pair["deltas"][target][metric] > threshold for pair in pairs)
    if regressions:
        decision, reason = "rejected", "Predefined regression threshold exceeded: " + ", ".join(regressions)
    elif target_passes >= consistent_count:
        decision, reason = "accepted", "Repeated workload improvement met all predefined thresholds"
    elif target_failures >= consistent_count:
        decision, reason = "rejected", "Workload measurements consistently missed the improvement threshold"
    else:
        decision, reason = "inconclusive", "Paired workload measurements disagree on the improvement threshold"
    return {
        "decision": decision, "reason": reason, "pairs": pairs,
        "median_paired_deltas": medians, "target_pairs_meeting_threshold": target_passes,
        "delta_units": {"timing": "percent", "allocation": "bytes per frame"},
    }

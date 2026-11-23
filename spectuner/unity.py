import csv
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from uuid import UUID

from .benchmark import frame_stats


WORKLOAD_TYPE = "SpecTuner.UnityDemo.NpcWorkload"
MEMBER_OPERATION = "inspect_managed_members"
LEGACY_CAPTURE_HEADER = (
    "scenario", "npc_count", "frame_index", "frame_ms", "fps", "workload_ms", "run_mode", "assembly_mvid",
)
CAPTURE_HEADER = (*LEGACY_CAPTURE_HEADER, "optimization_mode", "frame_alloc_bytes")


@dataclass(frozen=True)
class Frame:
    duration_ms: float
    workload_ms: float
    alloc_bytes: int | None = None


@dataclass(frozen=True)
class Capture:
    mode: str
    mvid: UUID
    groups: dict[tuple[str, int], list[Frame]]
    optimization_mode: str | None = None


@dataclass(frozen=True)
class ReaFinding:
    evidence_id: str
    sha256: str
    mvid: UUID | None
    coverage: str
    methods: int
    call_edges: int
    type_found: bool


def frame_tail_report(label: str, count: int, frames: list[Frame], budget_ms: float) -> list[str]:
    ranked = sorted(enumerate(frames), key=lambda item: item[1].duration_ms, reverse=True)
    total_ms = math.fsum(frame.duration_ms for frame in frames)
    slow = [item for item in ranked if item[1].duration_ms > budget_ms]
    slow_share = math.fsum(frame.duration_ms for _, frame in slow) / total_ms
    p99 = ranked[len(ranked) - math.ceil(0.99 * len(ranked))][1].duration_ms
    maximum = ranked[0][1].duration_ms
    lines = [
        f"- {label}, {count} NPCs: mean {total_ms / len(frames):.2f} ms, "
        f"P99 {p99:.2f} ms, max {maximum:.2f} ms, total {total_ms / 1000:.3f} s. "
        f"Over-budget frames account for {slow_share:.1%} of captured time.",
    ]
    lines.extend(
        f"  - Frame {index}: {frame.duration_ms:.2f} ms interval, {frame.workload_ms:.3f} ms NPC work."
        for index, frame in slow[:3]
    )
    return lines


def read_capture(path: Path) -> Capture:
    groups: dict[tuple[str, int], list[Frame]] = {}
    identity: tuple[str, UUID, str | None, bool] | None = None
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = csv.reader(stream, strict=True)
        header = tuple(next(rows, ()))
        if header not in (LEGACY_CAPTURE_HEADER, CAPTURE_HEADER):
            raise ValueError(f"{path}: expected a supported Unity CSV header")
        for row in rows:
            if not row:
                continue
            try:
                if len(row) != len(header):
                    raise ValueError(f"expected {len(header)} columns")
                scenario, count, index, duration, fps, workload, mode, mvid_text = row[:8]
                optimization_mode = None
                alloc_bytes = None
                if header == CAPTURE_HEADER:
                    optimization_mode, allocation = row[8:]
                    if optimization_mode not in {"baseline", "optimized"}:
                        raise ValueError("optimization_mode must be baseline or optimized")
                    if allocation:
                        alloc_bytes = int(allocation)
                        if alloc_bytes < 0:
                            raise ValueError("frame_alloc_bytes must be nonnegative")
                population, frame_index = int(count), int(index)
                frame_ms, fps_value, workload_ms = float(duration), float(fps), float(workload)
                mvid = UUID(mvid_text)
                if not scenario.strip() or population < 0 or mode not in {"editor", "player"} or not mvid.int:
                    raise ValueError("invalid scenario, NPC count, run mode or assembly MVID")
                if (
                    not all(math.isfinite(value) for value in (frame_ms, fps_value, workload_ms))
                    or frame_ms <= 0 or fps_value <= 0 or workload_ms < 0
                    or not math.isclose(fps_value, 1000.0 / frame_ms, rel_tol=1e-5)
                ):
                    raise ValueError("invalid timings or FPS inconsistent with frame_ms")
                current_identity = mode, mvid, optimization_mode, alloc_bytes is not None
                if identity is None:
                    identity = current_identity
                elif identity[:2] != current_identity[:2]:
                    raise ValueError("mixed run modes or assembly MVIDs in one capture")
                elif identity[2:] != current_identity[2:]:
                    raise ValueError("mixed optimization modes or allocation availability in one capture")
                group = groups.setdefault((scenario.strip(), population), [])
                if frame_index != len(group):
                    raise ValueError("frame_index must be consecutive from zero for each scenario and NPC count")
                group.append(Frame(frame_ms, workload_ms, alloc_bytes))
            except ValueError as error:
                raise ValueError(f"{path}:{rows.line_num}: {error}") from error
    if identity is None:
        raise ValueError(f"{path}: expected at least one captured frame")
    return Capture(identity[0], identity[1], groups, identity[2])


def read_rea_finding(path: Path) -> ReaFinding:
    try:
        evidence = json.loads(path.read_text(encoding="utf-8"))
        view = evidence["normalized_result"]
        if view["kind"] != "summary" or view["parent_operation"] != MEMBER_OPERATION:
            raise ValueError("expected an inspect-unity managed member summary")
        summary = view["summary"]
        selection = summary["selection"]
        counts = summary["reported_counts"]
        if selection["type_names"] != [WORKLOAD_TYPE]:
            raise ValueError(f"expected evidence scoped to {WORKLOAD_TYPE}")
        sha256 = summary["artifact"]["sha256"]
        methods, call_edges = counts["methods"], counts["call_edges"]
        coverage = summary["coverage"]["state"]
        evidence_id = view["parent_evidence_id"]
        if (
            not isinstance(sha256, str) or re.fullmatch(r"[a-fA-F0-9]{64}", sha256) is None
            or any(type(count) is not int or count < 0 for count in (methods, call_edges))
            or coverage not in {"complete", "partial", "unavailable"}
            or not isinstance(evidence_id, str) or not evidence_id
        ):
            raise ValueError("invalid evidence identity, coverage or reported counts")
        module = summary["module"]
        mvid = UUID(module["mvid"]) if module and module["mvid"] else None
        return ReaFinding(
            evidence_id, sha256, mvid, coverage, methods, call_edges,
            WORKLOAD_TYPE not in selection["unmatched_type_names"],
        )
    except (KeyError, TypeError, AttributeError, ValueError) as error:
        raise ValueError(f"{path}: invalid REA evidence ({error})") from error


def baseline_report(capture: Capture, target_fps: float, evidence: ReaFinding | None = None) -> str:
    if not math.isfinite(target_fps) or target_fps <= 0 or not math.isfinite(1000.0 / target_fps):
        raise ValueError("target FPS must give a positive, finite frame budget")
    budget_ms = 1000.0 / target_fps
    lines = [
        "## Runtime measurements (supplied CSV)",
        f"Run mode {capture.mode} | Waypoint search {capture.optimization_mode or 'unrecorded (legacy)'} | "
        f"Module MVID {capture.mvid} | "
        f"Frame budget {budget_ms:.2f} ms ({target_fps:g} FPS)",
        "",
        "| Scenario | NPCs | Frames | Throughput FPS | Median frame (ms) | P95 frame (ms) | Over budget | P95 NPC work (ms) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    over_budget = []
    npc_work: list[tuple[int, float]] = []
    tails: list[str] = []
    for (scenario, count), frames in sorted(capture.groups.items()):
        durations = [frame.duration_ms for frame in frames]
        timings = frame_stats(durations)
        workload = frame_stats([frame.workload_ms for frame in frames])
        misses = sum(frame > budget_ms for frame in durations)
        mean_fps = 1000.0 / fmean(durations)
        label = scenario.replace("|", r"\|").replace("\n", " ").replace("\r", " ")
        lines.append(
            f"| {label} | {count} | {timings.frames} | {mean_fps:.2f} | {timings.median_ms:.2f} | "
            f"{timings.p95_ms:.2f} | {misses}/{timings.frames} ({misses / timings.frames:.1%}) | "
            f"{workload.p95_ms:.3f} |"
        )
        if timings.p95_ms > budget_ms:
            over_budget.append(f"{label} at {count} NPCs")
        tails.extend(frame_tail_report(label, count, frames, budget_ms))
        if scenario == "npc-scan":
            npc_work.append((count, workload.p95_ms))
    lines.extend((
        "",
        "P95 exceeds the frame budget for " + ", ".join(over_budget) + "."
        if over_budget else "No recorded group had a P95 above the frame budget.",
        "",
        "## Frame-time tails",
        "Throughput FPS is frames divided by the sum of all captured frame intervals. "
        "Rare stalls can dominate it while leaving the median and P95 low. All intervals are retained. "
        "Up to three of the longest over-budget intervals per group are shown with zero-based CSV frame indices.",
        "",
        *tails,
        "",
        "## REA static findings",
    ))
    if evidence is None:
        lines.append("No REA evidence supplied.")
    else:
        match = (
            "Module MVID agrees with the capture (module identity only)."
            if evidence.mvid == capture.mvid else
            "Module MVID is absent or differs from the capture. Keep these findings separate from the run."
        )
        lines.extend((
            f"- Evidence {evidence.evidence_id} | Artifact SHA-256 {evidence.sha256}",
            f"- {match}",
            f"- {WORKLOAD_TYPE} {'matched' if evidence.type_found else 'unmatched'}. "
            f"Reported {evidence.methods} methods and {evidence.call_edges} static call edges. "
            f"Coverage {evidence.coverage}.",
            "- Static edges describe compiled structure. Runtime cost requires measurement.",
        ))
    lines.extend(("", "## Optimization targets to investigate"))
    if len(npc_work) >= 2:
        low_count, low_p95 = npc_work[0]
        high_count, high_p95 = npc_work[-1]
        lines.append(
            f"- The CSV shows NPC-work P95 of {low_p95:.3f} ms at {low_count} NPCs and "
            f"{high_p95:.3f} ms at {high_count} NPCs. Use repeated live captures to check this pattern."
        )
    if npc_work:
        lines.extend((
            "- Profile the fused waypoint scan in Unity Profiler and compare with a tagged baseline capture."
            if capture.optimization_mode == "optimized" else
            "- Source hypothesis from NpcWorkload.MeasureWaypoints: profile the per-NPC distance array in Unity "
            "Profiler (GC Alloc). Compare the fused scan with the original path.",
            "- If NPC work explains little of slow frames, inspect render-thread and GPU timings with the same load.",
        ))
    else:
        lines.append("- No demo NPC-scan captures were supplied. Profile the sections relevant to this capture.")
    lines.append(
        "Use compare-unity with both tagged captures to measure the mode difference."
        if capture.optimization_mode else "These are investigation targets. No optimization was applied or measured."
    )
    return "\n".join(lines)


def compare_unity_report(baseline: Capture, optimized: Capture) -> str:
    if (baseline.optimization_mode, optimized.optimization_mode) != ("baseline", "optimized"):
        raise ValueError("Pass a tagged baseline capture first and a tagged optimized capture second")
    if (baseline.mode, baseline.mvid) != (optimized.mode, optimized.mvid):
        raise ValueError("Unity captures must have the same run mode and assembly MVID")
    if baseline.groups.keys() != optimized.groups.keys():
        raise ValueError("Unity captures must have the same scenarios and NPC counts")

    lines = [
        "## Unity baseline vs optimized",
        f"Run mode {baseline.mode} | Module MVID {baseline.mvid}",
        "Delta is optimized minus baseline. All recorded frames are included.",
    ]
    for (scenario, count), before in sorted(baseline.groups.items()):
        after = optimized.groups[(scenario, count)]
        label = scenario.replace("|", r"\|").replace("\n", " ").replace("\r", " ")
        lines.extend((
            "",
            f"### {label}, {count} NPCs ({len(before)} → {len(after)} frames)",
            "",
            "| Metric | Baseline | Optimized | Delta | Change |",
            "| --- | ---: | ---: | ---: | ---: |",
        ))
        for metric, before_values, after_values in (
            ("Frame time (ms)", [frame.duration_ms for frame in before], [frame.duration_ms for frame in after]),
            ("NPC workload (ms)", [frame.workload_ms for frame in before], [frame.workload_ms for frame in after]),
            ("Managed bytes/frame", [frame.alloc_bytes for frame in before if frame.alloc_bytes is not None],
             [frame.alloc_bytes for frame in after if frame.alloc_bytes is not None]),
        ):
            old = frame_stats(before_values) if before_values else None
            new = frame_stats(after_values) if after_values else None
            for percentile, attr in (("P50", "median_ms"), ("P95", "p95_ms")):
                previous, current = getattr(old, attr, None), getattr(new, attr, None)
                if previous is None or current is None:
                    before_text = "unavailable" if previous is None else f"{previous:.3f}"
                    after_text = "unavailable" if current is None else f"{current:.3f}"
                    lines.append(f"| {percentile} {metric} | {before_text} | {after_text} | — | — |")
                    continue
                delta = current - previous
                percent = f"{delta / previous:+.2%}" if previous else "—"
                lines.append(f"| {percentile} {metric} | {previous:.3f} | {current:.3f} | {delta:+.3f} | {percent} |")
    lines.extend(("", "Allocation counts cover the whole frame, including managed work outside the NPC tick."))
    return "\n".join(lines)

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
CAPTURE_HEADER = (
    "scenario", "npc_count", "frame_index", "frame_ms", "fps", "workload_ms", "run_mode", "assembly_mvid",
)


@dataclass(frozen=True)
class Frame:
    duration_ms: float
    workload_ms: float


@dataclass(frozen=True)
class Capture:
    mode: str
    mvid: UUID
    groups: dict[tuple[str, int], list[Frame]]


@dataclass(frozen=True)
class ReaFinding:
    evidence_id: str
    sha256: str
    mvid: UUID | None
    coverage: str
    methods: int
    call_edges: int
    type_found: bool


def read_capture(path: Path) -> Capture:
    groups: dict[tuple[str, int], list[Frame]] = {}
    identity: tuple[str, UUID] | None = None
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = csv.reader(stream, strict=True)
        if tuple(next(rows, ())) != CAPTURE_HEADER:
            raise ValueError(f"{path}: expected Unity CSV header {','.join(CAPTURE_HEADER)}")
        for row in rows:
            if not row:
                continue
            try:
                scenario, count, index, duration, fps, workload, mode, mvid_text = row
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
                if identity is None:
                    identity = mode, mvid
                elif identity != (mode, mvid):
                    raise ValueError("mixed run modes or assembly MVIDs in one capture")
                group = groups.setdefault((scenario.strip(), population), [])
                if frame_index != len(group):
                    raise ValueError("frame_index must be consecutive from zero for each scenario and NPC count")
                group.append(Frame(frame_ms, workload_ms))
            except ValueError as error:
                raise ValueError(f"{path}:{rows.line_num}: {error}") from error
    if identity is None:
        raise ValueError(f"{path}: expected at least one captured frame")
    return Capture(*identity, groups)


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
        f"Run mode {capture.mode} | Module MVID {capture.mvid} | "
        f"Frame budget {budget_ms:.2f} ms ({target_fps:g} FPS)",
        "",
        "| Scenario | NPCs | Frames | Mean FPS | Median frame (ms) | P95 frame (ms) | Over budget | P95 NPC work (ms) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    over_budget = []
    npc_work: list[tuple[int, float]] = []
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
        if scenario == "npc-scan":
            npc_work.append((count, workload.p95_ms))
    lines.extend((
        "",
        "P95 exceeds the frame budget for " + ", ".join(over_budget) + "."
        if over_budget else "No recorded group had a P95 above the frame budget.",
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
            "- Source hypothesis from NpcWorkload.MeasureWaypoints: profile the per-NPC distance array in Unity "
            "Profiler (GC Alloc). Evaluate a single-pass squared-distance search with the same arrival threshold.",
            "- If NPC work explains little of slow frames, inspect render-thread and GPU timings with the same load.",
        ))
    else:
        lines.append("- No demo NPC-scan captures were supplied. Profile the sections relevant to this capture.")
    lines.append("These are investigation targets. No optimization was applied or measured.")
    return "\n".join(lines)

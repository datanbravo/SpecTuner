# Phase 3 waypoint analysis

## What the capture shows

The Unity Editor capture `unity-20261123-195316-fa3ef31d00404009b8981c68152ed86e.csv`
contains 10,876 frames, all associated with module MVID
`1a993903-5566-4ee4-a5ba-69cf15eab553`. CSV SHA-256
`056a3e6fac9e4785e92da85f9684b549443263a1eb15923549b4b3be5754f76a`.

| NPCs | Frames | Throughput FPS | Median frame (ms) | P95 frame (ms) | P99 frame (ms) | P95 NPC work (ms) | Time in frames over 16.67 ms |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 64 | 4,752 | 428.58 | 0.70 | 0.80 | 2.81 | 0.169 | 67.8% |
| 256 | 5,557 | 555.73 | 1.20 | 1.60 | 3.00 | 0.588 | 27.9% |
| 1,024 | 567 | 56.69 | 3.11 | 4.99 | 10.33 | 3.587 | 80.4% |

The reported FPS is correct for throughput: `567 / 10.001436 s = 56.69 FPS`.
This is equivalent to dividing 1,000 by the mean frame time of 17.639 ms.
It differs from averaging the reciprocal of each frame interval, which
would give 298.96 FPS and overweight short intervals. Median and P95 measure
the distribution by frame count and can leave a rare stall above their rank.

At 1,024 NPCs, zero-based frame 266 lasted **7,912.99 ms**, or **79.1%** of the
group's captured time, while the timed NPC section recorded **2.464 ms**.
Adjacent frames 265 and 267 lasted 104.27 and 22.78 ms. Dropping only frame
266 gives 271.01 FPS as a sensitivity check. The baseline retains that row
and every other sample. Multi-second intervals also appear at 64 and
256 NPCs, which helps explain why the 64-NPC group has lower throughput FPS
than the 256-NPC group despite shorter typical frame times.

The stopwatch in [BenchmarkRunner](../unity/Assets/Runtime/BenchmarkRunner.cs)
times the NPC update. The full interval comes from Unity's unscaled frame
delta. The captured intervals establish poor pacing in this run, and the
workload quantiles establish that the timed NPC section got more expensive
as population rose. The CSV does not identify the multi-second stall's
cause. Investigate Editor scheduling or focus, GC activity elsewhere in the
frame, rendering, and OS activity with a correlated timeline.

## What REA verified

REA 6.7.0 advertised `inspect_managed_members` as available. It parsed the
owned `SpecTuner.UnityDemo.dll` as managed PE/CLI through
`rea-dotnet-static`, the built-in managed static provider version 1.
The scoped `inspect_managed_members` evidence reported complete coverage
for `SpecTuner.UnityDemo.NpcWorkload`. The summary is a projection of the
same evidence. Additional native disassembly providers are unnecessary for
this managed artifact.

- DLL SHA-256 `f74190e33d8ef75bfa1f3aec9900ba4e327038c49f086fddee68e965d7810056`.
  The module MVID matches the CSV.
- Evidence record `ev_5f4d39641916ff810788b25afec8e8a67ad7f5c8fe3d63d5fec87b55dad201c6`.
  The selected type has three decoded method bodies and six static call edges.
- `Tick` calls `MeasureWaypoints` and `FindClosest`, and calls
  `Vector3.MoveTowards` while reading and writing `Transform.position`.
  `MeasureWaypoints` has a `newarr` anchor at IL offset 3 and a
  `Vector3.Distance` call at IL offset 23. The [source](../unity/Assets/Runtime/NpcWorkload.cs)
  shows a fresh distance array and two waypoint passes for each NPC.

These file-backed CIL facts identify a candidate in the same module as the
timing data. They establish neither native JIT behavior nor the cause of
the stalls. At 1,024 NPCs and 128 waypoints, the source requests 512 KiB of
float array payload per tick before object overhead, assuming each NPC
executes the loop once. Use Unity Profiler GC Alloc to measure the actual
allocation volume.

## Proposal only

Fuse distance calculation and nearest selection into one allocation-free
scan. Replace the two calls in `Tick` with a single call to the proposed
helper, keeping `MoveTowards`, NPC order and delta time unchanged.

```csharp
private static int FindClosestWaypoint(Vector3 position, Vector3[] waypoints)
{
    int closest = 0;
    float minimum = float.PositiveInfinity;
    for (int index = 0; index < waypoints.Length; index++)
    {
        float distance = Vector3.Distance(position, waypoints[index]);
        if (distance <= 0.1f || distance >= minimum)
            continue;
        minimum = distance;
        closest = index;
    }
    return closest;
}
```

Keep the existing float distance calculation and comparison order. This
preserves the inclusive arrival exclusion, first eligible index on ties,
and index-zero fallback. Squared distances can alter comparisons near
rounded thresholds or ties and are outside this proposal. For 128 waypoints
this removes the array and its second traversal while keeping the same
number of distance calculations. The proposal has not been applied.

## Reproduce and compare after approval

1. Reproduce the existing report from the repository root with the installed
   CLI. Use the editor DLL from the same capture. Save both summary and
   complete evidence if retaining review artifacts.

   ```sh
   capture="$HOME/Library/Application Support/DefaultCompany/unity/SpecTuner/unity-20261123-195316-fa3ef31d00404009b8981c68152ed86e.csv"
   dll=unity/Library/ScriptAssemblies/SpecTuner.UnityDemo.dll
   spectuner inspect-unity "$dll" > /tmp/spectuner-managed-summary.json
   spectuner inspect-unity --complete "$dll" > /tmp/spectuner-managed-complete.json
   spectuner baseline "$capture" --rea-evidence /tmp/spectuner-managed-summary.json --target-fps 60
   ```

2. Before timing a candidate build, compare old and new waypoint indices
   and movement steps at fixed deltas in Unity. Cover seeded positions,
   equal distances, values below/at/above 0.1, duplicate waypoints, and
   the all-ineligible index-zero fallback. Check exact equality because the
   arithmetic and iteration order should be unchanged.
3. Collect at least five baseline/candidate pairs, alternating which build
   goes first. Use the same Unity Editor version, machine, power mode, Game
   view resolution and focus, initial seed, 64/256/1,024 populations, warm-up
   and sample durations. Keep Profiler off for the timed runs. Keep every
   raw CSV and its matching DLL hash and MVID. Generate each report with
   the command above, changing the paths per build.
4. Compare the median of paired P95 NPC-work differences at 1,024 NPCs as
   the primary result. Record P95/P99 frame time, throughput FPS, budget
   misses, and worst intervals separately. In a separate profiler pair,
   compare GC Alloc in the `SpecTuner.NpcWorkload` marker. Investigate
   multi-second stalls on the profiler timeline and retain them in the
   primary reports. A candidate succeeds if behavior checks pass, the
   per-NPC array allocation is gone, and reduced workload time repeats
   across pairs. Claim a pacing improvement only if its own measurements
   support it.

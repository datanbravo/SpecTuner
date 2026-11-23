# Phase 4 Unity benchmark

This first paired Editor run of the waypoint optimization used Unity
`6000.0.85f2`. The [raw capture index](../evidence/phase4/README.md) records
the original filenames, provenance, frame counts, and SHA-256 checksums.
These two captures share the same compiled module and reproduce the reported
percentages. The older 22:56 UTC baseline and the untagged Phase 3 capture
are outside this pair.

## Measurements

Each cell shows baseline → optimized (percentage change relative to baseline).
P50 is the median and P95 uses nearest rank. Each run contributes all of its
recorded frames. Bytes come from Unity's whole-frame managed allocation
counter and incorporate other managed activity in the frame.

| NPCs | Frames | P50 frame (ms) | P95 frame (ms) | P50 NPC work (ms) | P95 NPC work (ms) | P50 and P95 managed bytes/frame |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 64 | 5,473 → 7,342 | 0.681 → 0.682 (+0.13%) | 0.802 → 0.801 (−0.12%) | 0.142 → 0.141 (−0.64%) | 0.165 → 0.153 (−7.03%) | 44,635 → 9,819 (−78.00%) |
| 256 | 8,384 → 8,443 | 1.104 → 1.182 (+7.03%) | 1.259 → 1.291 (+2.52%) | 0.542 → 0.553 (+2.12%) | 0.584 → 0.588 (+0.65%) | 149,083 → 9,819 (−93.41%) |
| 1,024 | 3,072 → 3,100 | 3.000 → 3.178 (+5.92%) | 4.577 → 3.529 (−22.90%) | 2.135 → 2.209 (+3.47%) | 3.636 → 2.305 (−36.59%) | 566,875 → 9,819 (−98.27%) |

Percentages use unrounded values. At 1,024 NPCs, the upper tail improved
in this pair while both frame-time and workload medians regressed. At
256 NPCs, both frame and workload percentiles regressed despite fewer
managed bytes. The captures cannot establish the cause of those regressions
or how consistently the differences repeat.

The 64-NPC baseline totals 301.318 seconds, including a 297.173-second
interval at zero-based frame 5,472. The optimized capture totals only
5.091 seconds. Both CSVs retain every sample. These unequal windows make
the 64-NPC pair unsuitable for a throughput conclusion or a reliable mode
comparison. The 256- and 1,024-NPC windows are about ten seconds each. One
Editor run per mode does not establish statistical significance or
standalone-player performance. Repeat with fixed settings and alternate
mode order to assess repeatability. The CSV cannot attribute all managed
allocation changes to the NPC tick or explain GC pauses.

## Implementation and REA

[NpcWorkload](../unity/Assets/Runtime/NpcWorkload.cs) retains the original
two-pass baseline. Optimized fuses the distance calculation and closest
eligible waypoint selection in one pass and removes the temporary float
array. The modes share `Vector3.Distance`, the inclusive 0.1 arrival
exclusion, first eligible index on exact ties, index-zero fallback,
and the same `Vector3.MoveTowards` step. The runner fixes the selected
mode at startup and uses the same waypoint seed and NPC counts.

The capture-matched `SpecTuner.UnityDemo.dll` has MVID
`55856bd0-027a-4366-94e4-098b17038f53` and SHA-256
`e19589b5c0989f84023ba3786f24f3dcacf0a0da2121a53c1297364f4ea4b807`.
REA's built-in managed provider `rea-dotnet-static` version 1 returned
evidence `ev_e912e8b1017013de2957680a7b697bc8e797a4135a0e577dc23adfc7d9518836`
with complete coverage for the selected `NpcWorkload` type, five method
bodies, and nine static call edges.

- `Tick` calls `SelectWaypoint` and `Vector3.MoveTowards`. The selector
  has edges to `MeasureWaypoints` and `FindClosest` for the baseline
  and to `FindClosestWaypoint` for the optimized path.
- `MeasureWaypoints` has a `newarr` anchor at IL offset 3.
  `FindClosestWaypoint` has no `newarr` instruction. Both distance
  paths retain a `Vector3.Distance` edge. These are static CIL observations.
  The Unity captures supply the runtime timings and allocation measurements.

## Verification and reproduction

Unity batch checks passed seven selection edge cases and 128 seeded
movement ticks across eight NPCs. They assert both the selected index and
the exact resulting transform position. Coverage includes threshold
boundaries, ties, duplicate waypoints, and the all-ineligible fallback.
The isolated selector check detected a managed allocation event on the
baseline path and none on the optimized path. All 29 Python tests passed,
including live REA inspection of the matching DLL.

Run from the repository root using the current installed CLI:

```sh
spectuner compare-unity \
  evidence/phase4/unity-baseline-20261123-230225-bd2ce15e842949c79aebce6089b583ca.csv \
  evidence/phase4/unity-optimized-20261123-230452-29e01ad597364526a1deca49879983fd.csv
spectuner inspect-unity --complete unity/Library/ScriptAssemblies/SpecTuner.UnityDemo.dll
```

The CSV comparison works from the checked-in evidence alone. The REA
command needs the local Unity DLL. A rebuild can change its MVID and
artifact hash. The [Unity walkthrough](../unity/README.md) covers fresh
paired captures and headless equivalence checks.

# Phase 2 Unity benchmark

This project is a top-down NPC stress scene. Each NPC scans the same 128
seeded waypoints, selects the nearest eligible point and moves toward it.
The demo intentionally uses a fresh distance array per NPC per frame.
The **Baseline** mode keeps that path. **Optimized** uses one pass with
the same `Vector3.Distance`, inclusive arrival exclusion, first-index
tie-breaking, and index-zero fallback. Both modes use the same waypoint
seed, NPC counts, and movement code.

## Run locally

1. In Unity Hub, install and activate the Editor version in
   `ProjectSettings/ProjectVersion.txt` using the [Unity download archive](https://unity.com/releases/editor/archive).
   Add the repository's `unity/` directory as an existing project and open it.
   Allow the Editor to import assets and compile the scripts.
2. Choose **SpecTuner → Open Benchmark Scene**. This creates a local scene
   on first use. In the Hierarchy select **SpecTuner Benchmark**. In the
   **Benchmark Runner** Inspector, set **Waypoint Search** to **Baseline**
   before entering Play mode. Open the **Game** tab, press **Play**, and keep
   it focused at a fixed resolution. Keep the Profiler closed for both
   measured modes. The runner fixes its mode at the start of each Play run.
3. Allow about 39 seconds for 64, 256 and 1024 NPCs, with 3 seconds of
   warm-up followed by 10 seconds of sampling per load. Keep Play active
   until the Console logs `SpecTuner capture written to …`. Copy that
   path. Captures are written under Unity's
   [persistent data directory](https://docs.unity.com/en-us/engine/6000.0/script-reference/unityengine/application/persistentdatapath),
   in a `SpecTuner` subdirectory.
4. Exit Play mode. Set **Waypoint Search** to **Optimized** on the same
   component, then repeat the run in the same Editor without recompiling.
   Keep both CSV paths. The names include `unity-baseline-` or
   `unity-optimized-` to help identify them.

The Editor run is the initial demonstration. For a separate standalone
experiment, add the generated scene to a macOS build profile, select the
Mono scripting backend, and point inspection at that player's copy of
`SpecTuner.UnityDemo.dll`. The managed inspection route expects a PE/CLI
assembly. Native executables and IL2CPP player code are outside its scope.
Keep Editor and player results separate.

## Report from the repository root

Use the Python environment from the [project setup](../README.md#setup).

```sh
spectuner baseline "/actual/path/to/unity-capture.csv"
spectuner inspect-unity unity/Library/ScriptAssemblies/SpecTuner.UnityDemo.dll > /tmp/spectuner-rea.json
spectuner baseline "/actual/path/to/unity-capture.csv" --rea-evidence /tmp/spectuner-rea.json --target-fps 60
spectuner compare-unity "/actual/path/to/unity-baseline.csv" "/actual/path/to/unity-optimized.csv"
```

`inspect-unity` uses the existing REA MCP registration and requests a
read-only managed member summary scoped to `SpecTuner.UnityDemo.NpcWorkload`.
Add `--complete` to export member rows, CIL anchors and call edges. Pass
the default summary output to `baseline --rea-evidence`.
Inspect the DLL from the capture's compilation. The report checks the
module version ID (MVID) against the CSV and keeps missing or mismatched
identity separate from the runtime measurements. Static method and call-edge
counts and coverage describe the compiled assembly; they cannot establish
hotness, allocations per frame or performance causation.

CSV columns are `scenario,npc_count,frame_index,frame_ms,fps,workload_ms,run_mode,assembly_mvid,optimization_mode,frame_alloc_bytes`.
Each row records one frame. Unity's
[unscaled frame delta](https://docs.unity.com/en-us/engine/6000.0/script-reference/unityengine/time/unscaleddeltatime)
supplies frame time and a stopwatch times the NPC update associated with that
interval. The per-frame FPS field is `1000 / frame_ms`. Reported throughput
FPS is frames divided by summed frame time. P95 and P99 use nearest rank.
The report retains stalls and shows their share of captured time. The runner requests uncapped desktop frame pacing
and writes CSV after all samples. Editor overhead, rendering changes with
population, and fixed scenario order can affect the results. Repeat runs at
the same resolution and settings before drawing conclusions.

The comparison reports P50 and P95 full frame time, NPC update time and
managed bytes per frame from Unity's **GC Allocated In Frame** recorder.
This allocation metric includes other managed work in the frame. An empty
`frame_alloc_bytes` means a complete set of counter samples was unavailable.
A zero is a measured counter value. Use the Unity Profiler's GC Alloc
column under `SpecTuner.NpcWorkload` to investigate allocation attribution.
[Unity Memory Profiler reference](https://docs.unity.com/en-us/engine/6000.0/manual/analysis/profiler/visualizing-data/memory/memory)

`compare-unity` requires an explicitly tagged baseline followed by an
optimized capture, with the same run mode, DLL MVID, scenario set and NPC
counts. Capture the baseline again in Phase 4 for a comparable pair.
Older CSVs still work with `baseline`. Repeat pairs in alternating order
to assess whether differences are consistent.

## Evidence and next measurements

The [Phase 3 report](../docs/phase3-waypoint-analysis.md) records the original
Unity capture, matching managed DLL evidence, and the before/after plan.
The [Phase 4 benchmark](../docs/phase4-benchmark.md) records the paired
Editor captures, REA findings, and observed regressions.
`examples/unity-synthetic.csv` remains a test fixture.

Run the movement equivalence checks from the Unity menu **SpecTuner →
Run Waypoint Equivalence Checks** outside Play mode. They exercise seven
edge cases and 128 seeded ticks, check exact waypoint indices and transform
positions, and check selector allocations in isolation when the counter
is available. They can also run headlessly without an extra Unity package.
Close this project in Unity before running the following command from
the repository root:

```sh
"/Applications/Unity/Hub/Editor/6000.0.85f2/Unity.app/Contents/MacOS/Unity" \
  -batchmode -nographics -projectPath "$PWD/unity" \
  -executeMethod SpecTuner.UnityDemo.WaypointChecks.RunBatch \
  -logFile /tmp/spectuner-waypoint-checks.log
```

Run the Python tests from the repository root. The live Unity tests
require a DLL compiled by this project.

```sh
python -m unittest discover -s tests -v
SPECTUNER_TEST_LIVE_REA=1 python -m unittest discover -s tests -v
SPECTUNER_TEST_UNITY_ASSEMBLY=unity/Library/ScriptAssemblies/SpecTuner.UnityDemo.dll \
  python -m unittest discover -s tests -p test_rea.py -v
```

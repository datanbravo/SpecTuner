# Phase 2 Unity benchmark

This project is a top-down NPC stress scene. Each NPC scans the same 128
seeded waypoints, selects the nearest eligible point and moves toward it.
The demo intentionally uses a fresh distance array per NPC per frame.

## Run locally

1. In Unity Hub, install and activate the Editor version in
   `ProjectSettings/ProjectVersion.txt` using the [Unity download archive](https://unity.com/releases/editor/archive).
   Add the repository's `unity/` directory as an existing project and open it.
   Allow the Editor to import assets and compile the scripts.
2. Choose **SpecTuner → Open Benchmark Scene**, open the **Game** tab, and
   press **Play**. This creates a local scene on first use. Keep the Game view
   focused at a fixed resolution. Close the Profiler for baseline runs.
3. Allow about 39 seconds for 64, 256 and 1024 NPCs, with 3 seconds of
   warm-up followed by 10 seconds of sampling per load. Keep Play active
   until the Console logs `SpecTuner capture written to …`. Copy that
   path. Captures are written under Unity's
   [persistent data directory](https://docs.unity.com/en-us/engine/6000.0/script-reference/unityengine/application/persistentdatapath),
   in a `SpecTuner` subdirectory.

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
```

`inspect-unity` uses the existing REA MCP registration and requests a
read-only managed member summary scoped to `SpecTuner.UnityDemo.NpcWorkload`.
Inspect the DLL from the capture's compilation. The report checks the
module version ID (MVID) against the CSV and keeps missing or mismatched
identity separate from the runtime measurements. Static method and call-edge
counts and coverage describe the compiled assembly; they cannot establish
hotness, allocations per frame or performance causation.

CSV columns are `scenario,npc_count,frame_index,frame_ms,fps,workload_ms,run_mode,assembly_mvid`.
Each row records one frame. Unity's
[unscaled frame delta](https://docs.unity.com/en-us/engine/6000.0/script-reference/unityengine/time/unscaleddeltatime)
supplies frame time and a stopwatch times the NPC update associated with that
interval. The per-frame FPS field is `1000 / frame_ms`. Reported mean FPS is
`1000 / mean(frame_ms)`. P95 uses nearest rank, and frames over the budget
are counted individually. The runner requests uncapped desktop frame pacing
and writes CSV after all samples. Editor overhead, rendering changes with
population, and fixed scenario order can affect the results. Repeat runs at
the same resolution and settings before drawing conclusions.

## Evidence and next measurements

- **Runtime measurements:** No real Unity capture was produced during initial
  implementation. `examples/unity-synthetic.csv` is a test fixture for the
  report and contains no measured results.
- **REA findings:** The managed MCP route is ready for the compiled demo DLL.
  No static findings from an actual Unity assembly were produced during
  initial implementation.
- **Source hypotheses:** The distance-array allocation and two waypoint
  passes in `NpcWorkload` are candidates. In a separate Unity Profiler run,
  inspect `SpecTuner.NpcWorkload` and GC Alloc to test them. If the workload
  sample is small while frame times rise, inspect rendering and GPU timing.
  No optimization or improvement has been measured.

Run tests from the repository root. The live Unity test requires a DLL
compiled by this project.

```sh
python -m unittest discover -s tests -v
SPECTUNER_TEST_LIVE_REA=1 python -m unittest discover -s tests -v
SPECTUNER_TEST_UNITY_ASSEMBLY=unity/Library/ScriptAssemblies/SpecTuner.UnityDemo.dll \
  python -m unittest discover -s tests -p test_rea.py -v
```

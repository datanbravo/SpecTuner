# Phase 6 experiment workflow

The first approved run passed the baseline and candidate Unity checks. It
is awaiting real paired captures, so its performance decision is
inconclusive. The local workspace stays outside Git.

The first experiment supports the Phase 5 proposal to compute
`deltaSeconds * 2f` once per `NpcWorkload.Tick`. Codex converts the
verified proposal into a typed edit recipe. SpecTuner renders the exact diff
from an allowlisted transformation and rejects arbitrary code, commands, and
other proposals. No Unity copies or source changes occur during preparation.

## 1. Prepare and review

Run from the repository root with the updated SpecTuner installed. Use the
matching DLL and benchmark inputs that generated the pending Phase 5 report.
If those inputs changed, generate a fresh plan before preparing an experiment.
Only a supported movement-step proposal can proceed in this release.

```sh
workspace=/tmp/spectuner-phase6-experiment
.venv/bin/spectuner experiment prepare \
  --workspace "$workspace" \
  --proposal /tmp/spectuner-phase5-plan.json \
  --assembly unity/Library/ScriptAssemblies/SpecTuner.UnityDemo.dll \
  --baseline evidence/phase4/unity-baseline-20261123-230225-bd2ce15e842949c79aebce6089b583ca.csv \
  --optimized evidence/phase4/unity-optimized-20261123-230452-29e01ad597364526a1deca49879983fd.csv
```

Pick a new workspace outside the checkout. Preparation re-runs REA through
MCP, checks the proposal against fresh source and capture evidence, and writes
`review.json` and `candidate.diff`. Read both before deciding whether to
approve. The review ID binds the exact patch, evidence, source snapshot,
workspace, and acceptance policy. Treat `review.json` as local review
material. It records input paths and the supplied plan.

## 2. Approve and run the isolated checks

Only run the following command after a human reviews and approves the patch.
Copy the displayed review ID and enter the reviewer's name.

```sh
.venv/bin/spectuner experiment run \
  --workspace "$workspace" \
  --approve '<review-id-from-prepare>' --reviewer 'Your name' \
  --unity-editor '/Applications/Unity/Hub/Editor/6000.0.85f2/Unity.app/Contents/MacOS/Unity'
```

The runner verifies the review ID, source snapshot, and input hashes again.
It creates two minimal Unity projects under the workspace, copies only the
known source and project inputs, edits only the candidate copy, then runs the
same fixed Unity batch checks on both. REA identifies the tested DLL in each
copy. Use the pinned Editor version and keep both copies closed during this
step. Compiler errors or explicit behavior failures in the candidate reject
the experiment. Missing checks, unavailable counters, or build inspection
failures are inconclusive. In either case the candidate source is restored
before the report is finalized where the copy is intact.

## 3. Record real captures and decide

The runner automates compilation and checks headlessly. Frame pacing in this
demo depends on the graphical Editor workload. The first release imports
captures from controlled graphical runs rather than treating headless
`-nographics` timing as comparable.

Open the workspace's `baseline` and `candidate` directories in Unity Hub.
For **both copies**, follow the [Unity walkthrough](../unity/README.md#run-locally)
and set **Waypoint Search** to **Optimized**. In this experiment, baseline
means the approved starting build, which already has the fused search.
Candidate means that build plus the reviewed hoist. Keep Unity version,
resolution, Game view focus, power mode and Profiler settings fixed.
Alternate which build runs first and keep five paired CSVs. Keep the builds
and source files unchanged after the automated checks. A recompile that
changes a checked DLL invalidates its capture identity.

```sh
.venv/bin/spectuner experiment finish --workspace "$workspace" \
  --pair /path/to/baseline-1.csv /path/to/candidate-1.csv \
  --pair /path/to/baseline-2.csv /path/to/candidate-2.csv \
  --pair /path/to/baseline-3.csv /path/to/candidate-3.csv \
  --pair /path/to/baseline-4.csv /path/to/candidate-4.csv \
  --pair /path/to/baseline-5.csv /path/to/candidate-5.csv
```

The report requires unique, build-matched Editor captures with all three NPC
loads and measured allocations. Each group needs at least 100 frames and an
8–13 second window. The longer window in a pair can be at most 1.25 times
the shorter. Acceptance requires at least 5% lower P95 NPC work at 1,024 NPCs
in at least 80% of pairs, with no median paired P50/P95 timing regression
over 2% or increase in median paired P95 allocation at any load.
Consistently missing the primary threshold or exceeding a regression limit
rejects the candidate. Missing, unsuitable, or inconsistent measurements
remain inconclusive. The policy is a repeatability gate rather than a
statistical significance test.

`report.json` contains the proposal, REA evidence, approved diff, policy,
test results and log hashes, build identities, capture hashes, metrics, and
decision. Rejection restores the changed source file in the candidate copy.
An inconclusive import leaves the copy available for retry. To abandon and
restore it, use `experiment finish --workspace "$workspace" --abandon`.
The Unity logs and generated build caches are retained as experiment artifacts.
If reusing a restored copy, let Unity reimport it. An accepted candidate
stays in the isolated copy until separately reviewed for integration.

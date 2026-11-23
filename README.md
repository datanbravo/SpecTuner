# SpecTuner

SpecTuner is a Python harness for performance work on an owned Unity game.
SpecTuner connects to REA over MCP, inspects owned artifacts and reports
frame timings. The [Unity benchmark walkthrough](unity/README.md) covers
the Phase 2 NPC demo, capture format, and managed DLL inspection.
The [Phase 3 report](docs/phase3-waypoint-analysis.md) documents the real capture,
the compiled workload evidence, and the proposed behavior-preserving change.
The [Phase 4 benchmark](docs/phase4-benchmark.md) records the implemented
optimization, paired measurements, and their limitations.

## Setup

Use Python 3.11 or newer. From the repository root, create a dedicated
environment and install SpecTuner as a regular package.

```sh
python3 -m venv .venv-spectuner
source .venv-spectuner/bin/activate
python -m pip install .
```

If an existing environment's `spectuner` launcher raises
`ModuleNotFoundError` after an editable install, activate that environment
and repair it with `python -m pip install --force-reinstall --no-deps .`
when its dependencies are already installed. On the affected Anaconda Python,
startup skipped the editable install's `.pth` file. A regular install puts
the package in `site-packages`. Verify it outside the checkout with:

```sh
(cd /tmp && env -u PYTHONPATH spectuner --help)
```

The live check reads the local stdio registration at `[mcp_servers.rea]` from
`$CODEX_HOME/config.toml` or `~/.codex/config.toml`. To use another trusted file,
pass `spectuner --config /path/to/config.toml rea-check`. The registration
provides the subprocess command, arguments, environment, working directory and
timeouts. SpecTuner launches its own MCP session through the
[Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk).
For an `npx` registration, the harness sets npm offline for the child process
and uses the existing cached REA package. The launcher needs access to that
cache. A missing or inaccessible cache can prevent the connection.

## Commands

```sh
spectuner doctor
spectuner rea-check
spectuner rea-check --tools
spectuner inspect examples/inspection-demo
spectuner compare examples/before.csv examples/after.csv
spectuner baseline examples/unity-synthetic.csv
```

- `doctor` checks local prerequisites without starting REA.
- `rea-check` initializes MCP, enumerates the advertised tool catalog and
  calls `binary_session` with empty arguments. It reports target state,
  provider candidates, session capabilities and tool availability counts.
  `--tools` includes each tool's availability and reason.
- `inspect` sends an explicitly selected local directory to REA's JavaScript
  static analyzer and prints its JSON evidence summary, including artifact hash,
  coverage and analysis statistics. The demo sources model a tiny game tick.
  The analyzer reads the sources without running them. Use owned artifacts only.
  This command covers JavaScript directories. Use `inspect-unity` for the
  managed DLL compiled from the Unity demo.
- `compare` reports frame count, median and nearest-rank p95 (rank
  `ceil(0.95 × N)`) for each scenario, with percentages relative to baseline.
  Negative percentages indicate lower frame times.
- `compare-unity BASELINE.csv OPTIMIZED.csv` reports P50/P95 frame time,
  NPC workload time, and managed allocations when available. The
  [Unity walkthrough](unity/README.md#run-locally) explains mode selection.

The bundled CSVs are **synthetic**. They contain five frame times per scenario
per file. Arena median moves from 22 to 18 ms and p95 from 35 to 24 ms. Menu
times stay the same. The exact CSV header is `scenario,frame_ms`. Include one
positive finite frame duration in milliseconds per row. Both captures must
contain the same scenario names, and frame counts may differ. For actual
comparisons, capture the same replay, device, settings and warm-up conditions.
The report is descriptive and performs no statistical significance test.

## Tests

```sh
python -m unittest discover -s tests -v
SPECTUNER_TEST_LIVE_REA=1 python -m unittest discover -s tests -p test_rea.py -v
```

The regular suite uses mock MCP sessions. The opt-in live test reads the local
registration, checks the real tool catalog and session status, and inspects
the bundled first-party demo.

## Path to an optimizer

The typed interfaces in `spectuner/contracts.py` define artifact identity,
evidence-backed findings, proposals, approvals bound to a baseline and change
digest, and rollback receipts. They are interfaces for future implementations.

Phase 2 reports timing observations alongside static REA findings and keeps
their attribution separate. A future AI planner can use repeated captures
and profiler evidence to draft changes to owned source or build
settings. A future executor should verify the exact approved baseline and
change, capture a restore point, apply in isolation, rebuild and compare a
repeatable workload. AI proposals, approval enforcement, applying changes,
automated benchmark runs and rollback are future work.

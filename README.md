# SpecTuner

SpecTuner is a Python harness for performance work on an owned Unity game.
Phase 1 connects to REA over MCP, statically inspects a small first-party
JavaScript artifact and compares exported frame times.

## Setup

Use Python 3.11 or newer. From the repository root, create a fresh environment
to keep the existing tracked `.venv` intact.

```sh
python3 -m venv .venv-spectuner
source .venv-spectuner/bin/activate
python -m pip install -e .
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
  This workflow covers JavaScript directories. Unity binaries are future work.
- `compare` reports frame count, median and nearest-rank p95 (rank
  `ceil(0.95 × N)`) for each scenario, with percentages relative to baseline.
  Negative percentages indicate lower frame times.

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

The next phase can correlate REA findings from an explicitly selected owned
Unity build with Unity profiler captures and rank bottleneck hypotheses. An
AI planner can then draft evidence-backed changes to owned source or build
settings. A future executor should verify the exact approved baseline and
change, capture a restore point, apply in isolation, rebuild and compare a
repeatable workload. Unity inspection, AI proposals, approval enforcement,
patching, benchmark capture and rollback are all future work.

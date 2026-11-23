# Phase 5 AI planner

The planner reads a tagged Unity baseline/optimized pair, inspects the matching
managed DLL through the registered REA MCP server, and asks a model for one
follow-up experiment. It checks the selected type, CIL coverage, and capture
MVID before asking. Methods are mapped to declarations in the demo's
`unity/Assets/Runtime/NpcWorkload.cs` by name. Reuse the source checkout from
the capture build, since an MVID match alone does not authenticate source text.

## Demonstration

Run from the SpecTuner repository root with the local Python environment
active. Use the matching Phase 4 DLL, or supply a fresh pair and that pair's
DLL after recompiling. A different MVID causes the command to stop before
sending a request.

```sh
codex login status
spectuner plan --provider codex \
  --assembly unity/Library/ScriptAssemblies/SpecTuner.UnityDemo.dll \
  --baseline evidence/phase4/unity-baseline-20261123-230225-bd2ce15e842949c79aebce6089b583ca.csv \
  --optimized evidence/phase4/unity-optimized-20261123-230452-29e01ad597364526a1deca49879983fd.csv \
  --output /tmp/spectuner-phase5-plan.json
```

Use a new output filename for each run. An existing file is preserved. The
Codex provider runs `codex exec` in an ephemeral, read-only scratch
directory with shell, apps and web search disabled. It honors the existing
Codex login and omits API-key environment variables. Model access depends on
the signed-in account, connectivity, and plan limits. Configure the
executable with `--codex-command`, model with `--model`, or timeout with
`--model-timeout`. Codex is the initial built-in `ModelProvider`.
[Codex non-interactive mode](https://developers.openai.com/codex/noninteractive)

Running `plan` sends the selected workload source, scoped CIL facts, and
derived benchmark statistics to the model account. It sends neither the full
CSV nor the DLL. The JSON report includes filenames and hashes, the REA
record identifier, evidence IDs, and the proposal. Review the
`proposed_modification`, `expected_benefit`, `risks` and
`validation_plan` against their cited facts. Model hypotheses remain
unmeasured. A capture window longer than 1.25 times its partner is flagged
and cannot be the sole supporting benchmark evidence. Even comparable
windows do not establish repeatability or method-level attribution.

The report is saved with approval pending. There is no edit or apply
operation. A future implementation requires explicit approval before changing
game code. The current default test suite mocks model calls.

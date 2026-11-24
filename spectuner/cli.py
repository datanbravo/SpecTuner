import argparse
import asyncio
import csv
import importlib.util
import json
import os
import shutil
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from .benchmark import compare, format_report, read_benchmark
from .config import ConfigError, default_config_path, load_registration
from .unity import baseline_report, compare_unity_report, read_capture, read_rea_finding


def _doctor(config_path: Path) -> int:
    print(f"Python {sys.version.split()[0]} ({sys.executable})")
    sdk = importlib.util.find_spec("mcp") is not None
    print(f"Python MCP SDK {'found' if sdk else 'missing'}")
    try:
        registration = load_registration(config_path)
    except ConfigError as error:
        print(error, file=sys.stderr)
        return 1
    print(f"REA stdio registration found in {config_path}")
    path = registration.env.get("PATH", os.environ.get("PATH", os.defpath))
    if registration.cwd is not None and not registration.cwd.is_dir():
        print("REA working directory is missing", file=sys.stderr)
        return 1
    command = Path(registration.command)
    if registration.cwd is not None and command.parent != Path(".") and not command.is_absolute():
        command = registration.cwd / command
    executable = shutil.which(str(command), path=path)
    print(f"REA launcher {executable or 'missing'}")
    return 0 if sdk and executable else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="spectuner")
    parser.add_argument("--config", type=Path, default=default_config_path(), help="path to trusted Codex config.toml")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="check local prerequisites without starting REA")
    rea = commands.add_parser("rea-check", help="connect to REA and call read-only binary_session")
    rea.add_argument("--tools", action="store_true", help="include per-tool availability in the JSON report")
    inspect = commands.add_parser("inspect", help="inspect an owned local JavaScript application directory")
    inspect.add_argument("directory", type=Path)
    unity = commands.add_parser("inspect-unity", help="statically inspect the owned demo's managed DLL")
    unity.add_argument("assembly", type=Path)
    unity.add_argument("--complete", action="store_true", help="include static member and call-edge rows")
    baseline = commands.add_parser("baseline", help="summarize a Unity capture and optional REA evidence")
    baseline.add_argument("capture", type=Path)
    baseline.add_argument("--target-fps", type=float, default=60)
    baseline.add_argument("--rea-evidence", type=Path)
    unity_compare = commands.add_parser("compare-unity", help="compare tagged Unity baseline and optimized captures")
    unity_compare.add_argument("baseline", type=Path)
    unity_compare.add_argument("optimized", type=Path)
    plan = commands.add_parser("plan", help="save an AI optimization proposal for review")
    plan.add_argument("--project-root", type=Path, default=Path.cwd(), help="SpecTuner checkout")
    plan.add_argument("--baseline", type=Path, required=True, help="tagged baseline CSV")
    plan.add_argument("--optimized", type=Path, required=True, help="tagged optimized CSV")
    plan.add_argument("--assembly", type=Path, required=True, help="matching managed Unity DLL")
    plan.add_argument("--output", type=Path, required=True, help="new JSON report outside the Unity project")
    plan.add_argument("--provider", choices=("codex",), default="codex")
    plan.add_argument("--model", help="override the provider's default model")
    plan.add_argument("--model-timeout", type=float, default=180, help="provider timeout in seconds")
    plan.add_argument("--codex-command", default="codex", help="Codex CLI executable")
    experiment = commands.add_parser("experiment", help="review and run an isolated Unity experiment")
    steps = experiment.add_subparsers(dest="experiment_step", required=True)
    prepare = steps.add_parser("prepare", help="verify a proposal and write the exact patch for review")
    prepare.add_argument("--workspace", type=Path, required=True)
    prepare.add_argument("--project-root", type=Path, default=Path.cwd())
    prepare.add_argument("--proposal", type=Path, required=True)
    prepare.add_argument("--baseline", type=Path, required=True)
    prepare.add_argument("--optimized", type=Path, required=True)
    prepare.add_argument("--assembly", type=Path, required=True)
    prepare.add_argument("--model")
    prepare.add_argument("--model-timeout", type=float, default=180)
    prepare.add_argument("--codex-command", default="codex")
    run = steps.add_parser("run", help="apply a human-approved patch and run Unity checks in two copies")
    run.add_argument("--workspace", type=Path, required=True)
    run.add_argument("--approve", required=True, help="exact review ID after inspecting candidate.diff")
    run.add_argument("--reviewer", required=True)
    run.add_argument("--unity-editor", type=Path, required=True)
    run.add_argument("--unity-timeout", type=float, default=300)
    finish = steps.add_parser("finish", help="import paired captures and evaluate the reviewed criteria")
    finish.add_argument("--workspace", type=Path, required=True)
    finish.add_argument("--pair", type=Path, nargs=2, action="append", default=[], metavar=("BASELINE", "CANDIDATE"))
    finish.add_argument("--abandon", action="store_true", help="restore the candidate copy without a benchmark decision")
    benchmark = commands.add_parser("compare", help="compare per-frame benchmark CSV files")
    benchmark.add_argument("before", type=Path)
    benchmark.add_argument("after", type=Path)
    args = parser.parse_args(argv)

    if args.command == "doctor":
        return _doctor(args.config)
    try:
        if args.command == "compare":
            print(format_report(compare(read_benchmark(args.before), read_benchmark(args.after))))
            return 0
        if args.command == "baseline":
            capture = read_capture(args.capture)
            findings = read_rea_finding(args.rea_evidence) if args.rea_evidence else None
            print(baseline_report(capture, args.target_fps, findings))
            return 0
        if args.command == "compare-unity":
            print(compare_unity_report(read_capture(args.baseline), read_capture(args.optimized)))
            return 0
        if importlib.util.find_spec("mcp") is None:
            raise ConfigError("Python MCP SDK is missing. Install SpecTuner with python -m pip install .")
        from .rea import ReaError, check_rea, inspect_directory, inspect_unity_assembly

        try:
            registration = load_registration(args.config)
            if args.command == "experiment":
                from .experiment import finish_experiment, prepare_experiment, run_experiment
                from .model import CodexProvider
                from .planner import PlanningInputs

                if args.experiment_step == "prepare":
                    review = asyncio.run(prepare_experiment(
                        registration, PlanningInputs(args.project_root, args.assembly, args.baseline, args.optimized),
                        args.proposal, args.workspace, CodexProvider(args.codex_command, args.model, args.model_timeout),
                    ))
                    print(review["review"]["patch"], end="")
                    print(f'Review ID {review["review_id"]}')
                    print(f"Review saved to {args.workspace / 'review.json'}. Approval required before applying.")
                    return 0
                if args.experiment_step == "run":
                    result = asyncio.run(run_experiment(
                        registration, args.workspace, args.approve, args.reviewer, args.unity_editor, args.unity_timeout,
                    ))
                else:
                    if args.abandon and args.pair:
                        raise ValueError("Use either --abandon or --pair")
                    result = finish_experiment(
                        args.workspace, [pair[0] for pair in args.pair], [pair[1] for pair in args.pair],
                        abandon=args.abandon,
                    )
                print(f'{result["state"]} · {result["decision"]} · {result["reason"]}')
                print(f"Report saved to {args.workspace / 'report.json'}")
                return 0
            if args.command == "plan":
                from .model import CodexProvider
                from .planner import PlanningInputs, check_report_destination, plan_optimization, save_report

                check_report_destination(args.output, args.project_root)
                inputs = PlanningInputs(args.project_root, args.assembly, args.baseline, args.optimized)
                provider = CodexProvider(args.codex_command, args.model, args.model_timeout)
                draft = asyncio.run(plan_optimization(registration, inputs, provider))
                save_report(args.output, draft)
                print(f"Proposal saved to {args.output} (pending approval)")
                return 0
            if args.command == "inspect":
                evidence = asyncio.run(inspect_directory(registration, args.directory))
                print(json.dumps(evidence, indent=2, ensure_ascii=True))
                return 0
            if args.command == "inspect-unity":
                evidence = asyncio.run(inspect_unity_assembly(registration, args.assembly, complete=args.complete))
                print(json.dumps(evidence, indent=2, ensure_ascii=True))
                return 0
            report = asyncio.run(check_rea(registration))
        except ReaError as error:
            print(error, file=sys.stderr)
            return 1
        output = asdict(report)
        output["advertised_tools"] = len(report.tools)
        output["available_tools"] = sum(tool.available for tool in report.tools)
        output["unavailable_by_reason"] = Counter(
            tool.reason or "unknown" for tool in report.tools if not tool.available
        )
        if not args.tools:
            del output["tools"]
        print(json.dumps(output, indent=2))
        return 0
    except (OSError, ValueError, csv.Error) as error:
        print(error, file=sys.stderr)
        return 1

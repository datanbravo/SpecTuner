import math
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Registration:
    command: str
    args: tuple[str, ...]
    env: dict[str, str]
    cwd: Path | None
    startup_timeout: float
    tool_timeout: float


def default_config_path() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "config.toml"


def _timeout(settings: dict, key: str, default: float) -> float:
    value = settings.get(key, default)
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ConfigError(f"{key} must be a positive finite number")
    return float(value)


def load_registration(path: Path) -> Registration:
    try:
        with path.open("rb") as config:
            settings = tomllib.load(config)["mcp_servers"]["rea"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ConfigError(f"Cannot read the REA registration in {path}: {error}") from error
    if not isinstance(settings, dict):
        raise ConfigError("mcp_servers.rea must be a TOML table")
    if settings.get("enabled") is False:
        raise ConfigError("The REA registration is disabled")
    command = settings.get("command")
    if "url" in settings or not isinstance(command, str) or not command.strip():
        raise ConfigError("Phase 1 requires a local stdio REA registration with a command")
    args = settings.get("args", [])
    env = settings.get("env", {})
    env_vars = settings.get("env_vars", [])
    cwd = settings.get("cwd")
    if (
        not isinstance(args, list) or any(not isinstance(arg, str) for arg in args)
        or not isinstance(env, dict) or any(not isinstance(value, str) for value in env.values())
        or not isinstance(env_vars, list) or any(not isinstance(name, str) for name in env_vars)
        or (cwd is not None and (not isinstance(cwd, str) or not cwd.strip()))
    ):
        raise ConfigError("Invalid args, env, env_vars, or cwd in the REA registration")
    child_env = {name: os.environ[name] for name in env_vars if name in os.environ} | env
    if Path(command).name in {"npx", "npx.cmd"}:
        child_env["npm_config_offline"] = "true"
    return Registration(
        command, tuple(args), child_env, Path(cwd).expanduser() if cwd else None,
        _timeout(settings, "startup_timeout_sec", 30),
        _timeout(settings, "tool_timeout_sec", 60),
    )

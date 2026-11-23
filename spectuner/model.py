import json
import math
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Protocol


class ModelError(ValueError):
    pass


class ModelProvider(Protocol):
    @property
    def name(self) -> str: ...

    def generate(self, prompt: str, schema: dict[str, Any]) -> object: ...


@dataclass(frozen=True)
class CodexProvider:
    command: str = "codex"
    model: str | None = None
    timeout: float = 180

    @property
    def name(self) -> str:
        return "codex"

    def generate(self, prompt: str, schema: dict[str, Any]) -> object:
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ModelError("Model timeout must be positive and finite")
        command = shutil.which(self.command)
        if command is None:
            raise ModelError(f"Codex executable not found: {self.command}")
        environment = {
            name: os.environ[name]
            for name in ("PATH", "HOME", "USER", "LOGNAME", "TMPDIR", "LANG", "LC_ALL", "CODEX_HOME")
            if name in os.environ
        }
        with TemporaryDirectory(prefix="spectuner-model-") as directory:
            root = Path(directory).resolve()
            schema_file = root / "schema.json"
            response = root / "response.json"
            schema_file.write_text(json.dumps(schema), encoding="utf-8")
            args = [
                os.path.abspath(command), "--no-daemon", "--ask-for-approval", "never", "exec",
                "--ignore-user-config", "--ignore-rules", "--ephemeral", "--skip-git-repo-check",
                "--sandbox", "read-only", "--disable", "shell_tool", "--disable", "apps",
                "-c", 'web_search="disabled"', "--cd", str(root), "--output-schema", str(schema_file),
                "--output-last-message", str(response),
            ]
            if self.model:
                args.extend(("--model", self.model))
            try:
                result = subprocess.run(
                    [*args, "-"], cwd=root, env=environment, input=prompt, text=True,
                    encoding="utf-8", errors="replace", capture_output=True, timeout=self.timeout, check=False,
                )
            except subprocess.TimeoutExpired as error:
                raise ModelError(f"Codex planning timed out after {self.timeout:g} seconds") from error
            except OSError as error:
                raise ModelError(f"Could not launch Codex: {error}") from error
            if result.returncode:
                raise ModelError(
                    f"Codex planning failed (exit {result.returncode}). Check codex login status, "
                    "network access, model availability and usage limits."
                )
            try:
                return json.loads(response.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise ModelError("Codex did not produce a readable JSON proposal") from error

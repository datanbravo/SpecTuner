import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from spectuner.config import ConfigError, load_registration


class RegistrationTests(unittest.TestCase):
    def load(self, content):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(content, encoding="utf-8")
            return load_registration(path)

    def test_loads_canonical_stdio_registration_and_forces_offline_npx(self):
        with patch.dict(os.environ, {"TEST_REA_HOME": "/example"}):
            registration = self.load("""
[mcp_servers.rea]
command = "npx"
args = ["-y", "rea-agents@6.7.0", "mcp"]
env_vars = ["TEST_REA_HOME"]
startup_timeout_sec = 15
tool_timeout_sec = 90

[mcp_servers.rea.env]
HOPPER_LAUNCHER_PATH = "/example/hopper"
""")
        self.assertEqual(registration.args, ("-y", "rea-agents@6.7.0", "mcp"))
        self.assertEqual(registration.startup_timeout, 15)
        self.assertEqual(registration.tool_timeout, 90)
        self.assertEqual(registration.env, {
            "TEST_REA_HOME": "/example",
            "HOPPER_LAUNCHER_PATH": "/example/hopper",
            "npm_config_offline": "true",
        })

    def test_rejects_missing_disabled_and_unsupported_registrations(self):
        for content in ("", '[mcp_servers.rea]\ncommand="rea"\nenabled=false',
                        '[mcp_servers.rea]\nurl="https://example.com"',
                        '[mcp_servers.rea]\ncommand="rea"\ntool_timeout_sec=-1'):
            with self.subTest(content=content), self.assertRaises(ConfigError):
                self.load(content)

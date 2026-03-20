from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from lsfg_vk_manager.discovery import discover_executables, is_candidate_executable


class DiscoveryTests(unittest.TestCase):
    def test_is_candidate_executable_skips_known_installers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "vc_redist.x64.exe"
            path.write_text("", encoding="utf-8")
            self.assertFalse(is_candidate_executable(path))

    def test_discover_executables_prefers_relevant_binaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            install_path = Path(tmp)
            (install_path / "bin64").mkdir()
            (install_path / "support").mkdir()
            (install_path / "bin64" / "CoolGame.exe").write_text("", encoding="utf-8")
            (install_path / "support" / "launcher.exe").write_text("", encoding="utf-8")
            shell_script = install_path / "coolgame.sh"
            shell_script.write_text("#!/bin/sh\n", encoding="utf-8")
            os.chmod(shell_script, 0o755)

            executables = discover_executables(install_path, "Cool Game")

            self.assertIn("bin64/CoolGame.exe", executables)
            self.assertIn("CoolGame.exe", executables)
            self.assertIn("coolgame.sh", executables)
            self.assertNotIn("launcher.exe", executables[:2])

    def test_discover_executables_limits_depth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            install_path = Path(tmp)
            deep_dir = install_path / "a" / "b" / "c" / "d" / "e"
            deep_dir.mkdir(parents=True)
            (deep_dir / "TooDeep.exe").write_text("", encoding="utf-8")

            executables = discover_executables(install_path, "Deep Game")

            self.assertEqual(executables, [])


if __name__ == "__main__":
    unittest.main()

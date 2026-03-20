from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lsfg_vk_manager.settings import SettingsStore, SourceSettings, inspect_source_warnings, validate_sources


class SettingsStoreTests(unittest.TestCase):
    def test_write_and_reload_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.toml"
            with patch("lsfg_vk_manager.settings.detect_default_gpu", return_value="GPU Default"):
                store = SettingsStore(path)
            store.sources.steam_apps = "/tmp/steamapps"
            store.sources.steam_common = "/tmp/common"
            store.sources.hytale_release = "/tmp/hytale"
            store.sources.lsfg_config = "/tmp/conf.toml"
            store.sources.default_gpu = "GPU Custom"
            store.write()

            with patch("lsfg_vk_manager.settings.detect_default_gpu", return_value="GPU Other"):
                reloaded = SettingsStore(path)
            self.assertEqual(reloaded.sources.steam_apps, "/tmp/steamapps")
            self.assertEqual(reloaded.sources.steam_common, "/tmp/common")
            self.assertEqual(reloaded.sources.hytale_release, "/tmp/hytale")
            self.assertEqual(reloaded.sources.lsfg_config, "/tmp/conf.toml")
            self.assertEqual(reloaded.sources.default_gpu, "GPU Custom")
            self.assertEqual(reloaded.sources.lossless_dll_path, Path("/tmp/common/Lossless Scaling/Lossless.dll"))

    def test_missing_default_gpu_uses_detected_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.toml"
            path.write_text(
                '\n'.join(
                    [
                        "[sources]",
                        'steam_apps = "/tmp/steamapps"',
                        'steam_common = "/tmp/common"',
                        'hytale_release = "/tmp/hytale"',
                        'lsfg_config = "/tmp/conf.toml"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            with patch("lsfg_vk_manager.settings.detect_default_gpu", return_value="Detected GPU"):
                reloaded = SettingsStore(path)

            self.assertEqual(reloaded.sources.default_gpu, "Detected GPU")

    def test_validate_sources_reports_only_blocking_issues(self) -> None:
        sources = SourceSettings(
            steam_apps="/missing/steamapps",
            steam_common="/missing/common",
            hytale_release="/missing/hytale",
            lsfg_config="/missing/conf/conf.toml",
            default_gpu="",
        )

        issues = validate_sources(sources)

        self.assertIn("Default GPU: value cannot be empty", issues)
        self.assertEqual(len(issues), 1)

    def test_inspect_source_warnings_reports_missing_paths(self) -> None:
        sources = SourceSettings(
            steam_apps="/missing/steamapps",
            steam_common="/missing/common",
            hytale_release="/missing/hytale",
            lsfg_config="/missing/conf/conf.toml",
            default_gpu="GPU Custom",
        )

        warnings = inspect_source_warnings(sources)

        self.assertIn("Steam steamapps: path does not exist", warnings)
        self.assertIn("Steam common: path does not exist", warnings)
        self.assertIn("Hytale release: path does not exist", warnings)
        self.assertIn("lsfg-vk conf.toml: parent directory does not exist", warnings)

    def test_invalid_toml_uses_detected_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.toml"
            path.write_text("[sources\nbroken = true\n", encoding="utf-8")

            with patch("lsfg_vk_manager.settings.detect_default_gpu", return_value="Detected GPU"):
                store = SettingsStore(path)

            self.assertEqual(store.sources.default_gpu, "Detected GPU")
            self.assertEqual(store.sources.steam_apps, str(store.sources.steam_apps_path))


if __name__ == "__main__":
    unittest.main()

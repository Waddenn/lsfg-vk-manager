from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lsfg_vk_manager.settings import SettingsStore


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


if __name__ == "__main__":
    unittest.main()

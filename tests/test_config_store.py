from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lsfg_vk_manager.config_store import ConfigStore
from lsfg_vk_manager.models import Game, Profile


class ConfigStoreTests(unittest.TestCase):
    def test_save_games_preserves_unmanaged_profiles_and_writes_managed_ones(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "conf.toml"
            store = ConfigStore(config_path)
            store.profiles = [
                Profile(
                    name="Custom unmanaged",
                    active_in=["custom.exe"],
                    multiplier=3,
                    flow_scale=0.8,
                    performance_mode=True,
                    pacing="none",
                    gpu="GPU X",
                ),
                Profile(
                    name="Old managed",
                    active_in=["game.exe"],
                    managed_appid="123",
                ),
            ]

            game = Game(
                appid="123",
                name="Test Game",
                installdir="Test Game",
                install_path=Path(tmp) / "game",
                executables=["bin/TestGame.exe", "TestGame.exe"],
                enabled=True,
                profile_name="Test Game 2x FG",
                multiplier=4,
                flow_scale=0.75,
                performance_mode=True,
                pacing="none",
                gpu="GPU Y",
            )

            store.save_games([game])

            self.assertEqual(len(store.profiles), 2)
            self.assertEqual(store.profiles[0].name, "Custom unmanaged")
            self.assertEqual(store.profiles[1].managed_appid, "123")
            self.assertEqual(store.profiles[1].multiplier, 4)
            self.assertEqual(store.profiles[1].flow_scale, 0.75)

            reloaded = ConfigStore(config_path)
            self.assertEqual(len(reloaded.profiles), 2)
            managed = reloaded.profiles[1]
            self.assertEqual(managed.name, "Test Game 2x FG")
            self.assertEqual(managed.active_in, ["bin/TestGame.exe", "TestGame.exe"])
            self.assertTrue(managed.performance_mode)

    def test_load_supports_single_string_active_in(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "conf.toml"
            config_path.write_text(
                '\n'.join(
                    [
                        "version = 2",
                        "",
                        "[global]",
                        'dll = "/tmp/Lossless.dll"',
                        "allow_fp16 = true",
                        "",
                        "[[profile]]",
                        'name = "Single Exec"',
                        'active_in = "game.exe"',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            store = ConfigStore(config_path)

            self.assertEqual(store.profiles[0].active_in, ["game.exe"])

    def test_save_games_uses_manually_edited_executables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "conf.toml"
            store = ConfigStore(config_path)

            game = Game(
                appid="123",
                name="Editable Game",
                installdir="Editable Game",
                install_path=Path(tmp) / "game",
                executables=["custom/path/Game.sh"],
                detected_executables=["bin/Game.exe", "Game.exe"],
                enabled=True,
                profile_name="Editable Game 2x FG",
            )

            store.save_games([game])

            reloaded = ConfigStore(config_path)
            self.assertEqual(reloaded.profiles[0].active_in, ["custom/path/Game.sh"])


if __name__ == "__main__":
    unittest.main()

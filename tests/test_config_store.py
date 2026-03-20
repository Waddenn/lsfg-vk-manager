from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lsfg_vk_manager.config_store import ConfigStore
from lsfg_vk_manager.models import Game, Profile
from lsfg_vk_manager.settings import ManagedProfileMetadata


class ConfigStoreTests(unittest.TestCase):
    def test_load_supports_v1_game_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "conf.toml"
            config_path.write_text(
                '\n'.join(
                    [
                        "version = 1",
                        'dll = "/tmp/Lossless.dll"',
                        "",
                        '# lsfg-vk-manager name = "Stable Entry"',
                        '# lsfg-vk-manager managed_appid = "123"',
                        "[[game]]",
                        'exe = "game.sh"',
                        "multiplier = 3",
                        "flow_scale = 0.75",
                        "performance_mode = true",
                        "hdr_mode = false",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            metadata: dict[str, ManagedProfileMetadata] = {}
            store = ConfigStore(config_path, managed_metadata=metadata)

            self.assertEqual(store.version, 1)
            self.assertEqual(store.global_conf["dll"], "/tmp/Lossless.dll")
            self.assertEqual(len(store.profiles), 1)
            self.assertEqual(store.profiles[0].name, "Stable Entry")
            self.assertEqual(store.profiles[0].active_in, ["game.sh"])
            self.assertEqual(store.profiles[0].managed_appid, "123")
            self.assertTrue(store.profiles[0].performance_mode)
            self.assertIn("123", metadata)
            self.assertEqual(metadata["123"].executables, ["game.sh"])

    def test_save_games_preserves_unmanaged_profiles_and_writes_managed_ones(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "conf.toml"
            store = ConfigStore(config_path)
            store.version = 2
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
            store.version = 2

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

    def test_save_games_preserves_matching_unmanaged_profile_without_duplication(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "conf.toml"
            store = ConfigStore(config_path)
            store.version = 2
            unmanaged = Profile(
                name="Existing custom profile",
                active_in=["bin/Game.exe", "Game.exe"],
                multiplier=3,
                flow_scale=0.85,
                performance_mode=True,
                pacing="latency",
                gpu="GPU Z",
            )
            store.profiles = [unmanaged]

            game = Game(
                appid="123",
                name="Test Game",
                installdir="Test Game",
                install_path=Path(tmp) / "game",
                executables=["bin/Game.exe", "Game.exe"],
                enabled=True,
                profile_name="Existing custom profile",
                multiplier=3,
                flow_scale=0.85,
                performance_mode=True,
                pacing="latency",
                gpu="GPU Z",
                matched_profile_name=unmanaged.name,
                matched_profile=unmanaged,
            )

            store.save_games([game])

            self.assertEqual(len(store.profiles), 1)
            self.assertIsNone(store.profiles[0].managed_appid)
            self.assertEqual(store.profiles[0].name, "Existing custom profile")

    def test_save_games_writes_v1_entries_with_manager_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "conf.toml"
            store = ConfigStore(config_path)
            store.version = 1

            game = Game(
                appid="123",
                name="Stable Game",
                installdir="Stable Game",
                install_path=Path(tmp) / "game",
                executables=["bin/Game.sh", "Game.sh"],
                enabled=True,
                profile_name="Stable Game 2x FG",
                multiplier=3,
                flow_scale=0.7,
                performance_mode=True,
            )

            store.save_games([game])

            text = config_path.read_text(encoding="utf-8")
            self.assertIn("version = 1", text)
            self.assertIn('exe = "bin/Game.sh"', text)
            self.assertIn('exe = "Game.sh"', text)
            self.assertNotIn("lsfg-vk-manager", text)

            metadata = store.managed_metadata
            reloaded = ConfigStore(config_path, managed_metadata=metadata)
            self.assertEqual(reloaded.version, 1)
            managed = [profile for profile in reloaded.profiles if profile.managed_appid == "123"]
            self.assertEqual(len(managed), 2)
            self.assertEqual(managed[0].name, "Stable Game 2x FG")
            self.assertTrue(all(profile.performance_mode for profile in managed))

    def test_load_invalid_toml_falls_back_to_empty_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "conf.toml"
            config_path.write_text("[global\nbroken = true\n", encoding="utf-8")

            store = ConfigStore(config_path)

            self.assertEqual(store.profiles, [])
            self.assertEqual(store.global_conf["dll"], str(store.default_dll))


if __name__ == "__main__":
    unittest.main()

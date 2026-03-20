from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lsfg_vk_manager.config_store import ConfigStore
from lsfg_vk_manager.library import load_games
from lsfg_vk_manager.models import Profile
from lsfg_vk_manager.settings import SourceSettings


class LibraryTests(unittest.TestCase):
    def test_load_games_reads_manifests_and_matches_existing_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            steam_apps = root / "steamapps"
            steam_common = steam_apps / "common"
            steam_apps.mkdir(parents=True)
            steam_common.mkdir(parents=True)

            manifest = steam_apps / "appmanifest_100.acf"
            manifest.write_text(
                '\n'.join(
                    [
                        '"AppState"',
                        "{",
                        '    "appid" "100"',
                        '    "name" "Cool Game"',
                        '    "installdir" "Cool Game"',
                        "}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            config = ConfigStore(root / "conf.toml")
            sources = SourceSettings(
                steam_apps=str(steam_apps),
                steam_common=str(steam_common),
                hytale_release=str(root / "missing-hytale"),
                ryujinx_config=str(root / "missing-ryujinx/Config.json"),
                lsfg_config=str(root / "conf.toml"),
                default_gpu="GPU Default",
            )
            config.profiles = [
                Profile(
                    name="Existing profile",
                    active_in=["CoolGame.exe"],
                    multiplier=3,
                    flow_scale=0.9,
                    performance_mode=True,
                    pacing="none",
                    gpu="GPU Z",
                )
            ]

            with patch("lsfg_vk_manager.library.discover_executables", return_value=["bin/CoolGame.exe", "CoolGame.exe"]):
                games = load_games(config, sources)

            self.assertEqual(len(games), 1)
            game = games[0]
            self.assertEqual(game.appid, "100")
            self.assertTrue(game.enabled)
            self.assertEqual(game.profile_name, "Existing profile")
            self.assertEqual(game.multiplier, 3)
            self.assertEqual(game.gpu, "GPU Z")

    def test_load_games_skips_proton_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            steam_apps = root / "steamapps"
            steam_common = steam_apps / "common"
            steam_apps.mkdir(parents=True)
            steam_common.mkdir(parents=True)

            manifest = steam_apps / "appmanifest_200.acf"
            manifest.write_text(
                '\n'.join(
                    [
                        '"AppState"',
                        "{",
                        '    "appid" "200"',
                        '    "name" "Proton Experimental"',
                        '    "installdir" "Proton Experimental"',
                        "}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            config = ConfigStore(root / "conf.toml")
            sources = SourceSettings(
                steam_apps=str(steam_apps),
                steam_common=str(steam_common),
                hytale_release=str(root / "missing-hytale"),
                ryujinx_config=str(root / "missing-ryujinx/Config.json"),
                lsfg_config=str(root / "conf.toml"),
                default_gpu="GPU Default",
            )

            games = load_games(config, sources)

            self.assertEqual(games, [])

    def test_load_games_prefers_steam_launch_executables_from_appinfo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            steam_apps = root / "steamapps"
            steam_common = steam_apps / "common"
            steam_apps.mkdir(parents=True)
            steam_common.mkdir(parents=True)

            manifest = steam_apps / "appmanifest_300.acf"
            manifest.write_text(
                '\n'.join(
                    [
                        '"AppState"',
                        "{",
                        '    "appid" "300"',
                        '    "name" "Cool Game"',
                        '    "installdir" "Cool Game"',
                        "}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            config = ConfigStore(root / "conf.toml")
            sources = SourceSettings(
                steam_apps=str(steam_apps),
                steam_common=str(steam_common),
                hytale_release=str(root / "missing-hytale"),
                ryujinx_config=str(root / "missing-ryujinx/Config.json"),
                lsfg_config=str(root / "conf.toml"),
                default_gpu="GPU Default",
            )

            with (
                patch("lsfg_vk_manager.library.get_install_valid_launch_executables", return_value=["Game.x86_64"]),
                patch("lsfg_vk_manager.library.discover_executables", return_value=["Fallback.exe"]),
            ):
                games = load_games(config, sources)

            self.assertEqual(games[0].detected_executables, ["Game.x86_64"])

    def test_load_games_discovers_ryujinx_titles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            steam_apps = root / "steamapps"
            steam_common = steam_apps / "common"
            steam_apps.mkdir(parents=True)
            steam_common.mkdir(parents=True)

            ryujinx_root = root / "Ryujinx"
            ryujinx_games = ryujinx_root / "games"
            ryujinx_games.mkdir(parents=True)
            (ryujinx_games / "0100152000022000").mkdir()
            switch_dir = root / "Switch"
            mk_dir = switch_dir / "Mario Kart 8 Deluxe [0100152000022000]"
            mk_dir.mkdir(parents=True)
            (mk_dir / "Mario Kart 8 Deluxe [0100152000022000].xci").write_text("", encoding="utf-8")
            (ryujinx_root / "Config.json").write_text(
                '{\n  "game_dirs": ["' + str(switch_dir).replace("\\", "\\\\") + '"]\n}\n',
                encoding="utf-8",
            )

            config = ConfigStore(root / "conf.toml")
            sources = SourceSettings(
                steam_apps=str(steam_apps),
                steam_common=str(steam_common),
                hytale_release=str(root / "missing-hytale"),
                ryujinx_config=str(ryujinx_root / "Config.json"),
                lsfg_config=str(root / "conf.toml"),
                default_gpu="GPU Default",
            )

            games = load_games(config, sources)

            self.assertEqual(len(games), 1)
            game = games[0]
            self.assertEqual(game.appid, "custom:ryujinx:0100152000022000")
            self.assertEqual(game.name, "Mario Kart 8 Deluxe [Ryujinx]")
            self.assertEqual(game.install_path.name, "Mario Kart 8 Deluxe [0100152000022000].xci")
            self.assertEqual(game.executables, ["ryujinx-mario-kart-8-deluxe-0100152000022000"])

    def test_load_games_matches_managed_ryujinx_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            steam_apps = root / "steamapps"
            steam_common = steam_apps / "common"
            steam_apps.mkdir(parents=True)
            steam_common.mkdir(parents=True)

            ryujinx_root = root / "Ryujinx"
            ryujinx_games = ryujinx_root / "games"
            ryujinx_games.mkdir(parents=True)
            (ryujinx_games / "0100000000010000").mkdir()
            switch_dir = root / "Switch"
            odyssey_dir = switch_dir / "Super Mario Odyssey[0100000000010000]"
            odyssey_dir.mkdir(parents=True)
            (odyssey_dir / "Super Mario Odyssey[0100000000010000].nsp").write_text("", encoding="utf-8")
            (ryujinx_root / "Config.json").write_text(
                '{\n  "game_dirs": ["' + str(switch_dir).replace("\\", "\\\\") + '"]\n}\n',
                encoding="utf-8",
            )

            config = ConfigStore(root / "conf.toml")
            sources = SourceSettings(
                steam_apps=str(steam_apps),
                steam_common=str(steam_common),
                hytale_release=str(root / "missing-hytale"),
                ryujinx_config=str(ryujinx_root / "Config.json"),
                lsfg_config=str(root / "conf.toml"),
                default_gpu="GPU Default",
            )
            config.profiles = [
                Profile(
                    name="Super Mario Odyssey 2x FG",
                    active_in=["ryujinx-super-mario-odyssey-0100000000010000"],
                    multiplier=2,
                    managed_appid="custom:ryujinx:0100000000010000",
                )
            ]

            games = load_games(config, sources)

            self.assertEqual(len(games), 1)
            self.assertTrue(games[0].enabled)
            self.assertEqual(games[0].profile_source, "managed")
if __name__ == "__main__":
    unittest.main()

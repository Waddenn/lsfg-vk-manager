from __future__ import annotations

import unittest
from pathlib import Path

from lsfg_vk_manager.models import Game
from lsfg_vk_manager.ui import (
    AUTOSAVE_DELAY_MS,
    SaveIndicatorState,
    apply_enabled_state_to_games,
    compute_save_indicator,
    describe_profile_source,
    make_game_form_state,
)


class UiLogicTests(unittest.TestCase):
    def test_make_game_form_state_normalizes_values(self) -> None:
        game = Game(
            appid="1",
            name="Cool Game",
            installdir="Cool Game",
            install_path=Path("/tmp/game"),
            executables=["bin/CoolGame.sh"],
            enabled=True,
            profile_name="",
            flow_scale=0.756,
            gpu="",
        )

        state = make_game_form_state(game, "GPU Default")

        self.assertEqual(state.profile_name, "Cool Game 2x FG")
        self.assertEqual(state.flow_scale, 0.76)
        self.assertEqual(state.gpu, "GPU Default")

    def test_describe_profile_source_distinguishes_existing_profile(self) -> None:
        game = Game(
            appid="1",
            name="Cool Game",
            installdir="Cool Game",
            install_path=Path("/tmp/game"),
            executables=["CoolGame.exe"],
            enabled=True,
            matched_profile_name="Existing profile",
            profile_source="existing",
        )

        self.assertEqual(describe_profile_source(game), "Using existing profile: Existing profile")

    def test_autosave_delay_is_long_enough_for_typing(self) -> None:
        self.assertGreaterEqual(AUTOSAVE_DELAY_MS, 800)

    def test_compute_save_indicator_reports_saved_state(self) -> None:
        game = Game(
            appid="1",
            name="Cool Game",
            installdir="Cool Game",
            install_path=Path("/tmp/game"),
            executables=["CoolGame.exe"],
            enabled=True,
        )
        state = make_game_form_state(game, "GPU Default")

        indicator = compute_save_indicator(game, state, "GPU Default", autosave_pending=False)

        self.assertEqual(indicator, SaveIndicatorState("Saved", "success"))

    def test_compute_save_indicator_reports_saving_while_autosave_is_pending(self) -> None:
        game = Game(
            appid="1",
            name="Cool Game",
            installdir="Cool Game",
            install_path=Path("/tmp/game"),
            executables=["CoolGame.exe"],
            enabled=True,
            profile_name="Changed",
        )

        indicator = compute_save_indicator(game, None, "GPU Default", autosave_pending=True)

        self.assertEqual(indicator, SaveIndicatorState("Saving…", "accent"))

    def test_apply_enabled_state_to_games_enables_defaults_for_managed_profiles(self) -> None:
        game = Game(
            appid="1",
            name="Cool Game",
            installdir="Cool Game",
            install_path=Path("/tmp/game"),
            executables=[],
            detected_executables=["CoolGame.exe"],
            enabled=False,
            gpu="",
            pacing="",
        )

        changed = apply_enabled_state_to_games([game], True, "GPU Default")

        self.assertEqual(changed, 1)
        self.assertTrue(game.enabled)
        self.assertEqual(game.profile_name, "Cool Game 2x FG")
        self.assertEqual(game.executables, ["CoolGame.exe"])
        self.assertEqual(game.gpu, "GPU Default")
        self.assertEqual(game.pacing, "none")
        self.assertEqual(game.profile_source, "managed")

    def test_apply_enabled_state_to_games_preserves_existing_profile_source(self) -> None:
        game = Game(
            appid="1",
            name="Cool Game",
            installdir="Cool Game",
            install_path=Path("/tmp/game"),
            executables=["CoolGame.exe"],
            enabled=False,
            profile_source="existing",
            matched_profile_name="Custom",
        )

        changed = apply_enabled_state_to_games([game], True, "GPU Default")

        self.assertEqual(changed, 1)
        self.assertTrue(game.enabled)
        self.assertEqual(game.profile_source, "existing")

    def test_apply_enabled_state_to_games_disables_all_targets(self) -> None:
        first = Game(
            appid="1",
            name="First",
            installdir="First",
            install_path=Path("/tmp/first"),
            executables=["First.exe"],
            enabled=True,
            profile_source="managed",
        )
        second = Game(
            appid="2",
            name="Second",
            installdir="Second",
            install_path=Path("/tmp/second"),
            executables=["Second.exe"],
            enabled=True,
            profile_source="existing",
        )

        changed = apply_enabled_state_to_games([first, second], False, "GPU Default")

        self.assertEqual(changed, 2)
        self.assertFalse(first.enabled)
        self.assertFalse(second.enabled)
        self.assertIsNone(first.profile_source)
        self.assertIsNone(second.profile_source)


if __name__ == "__main__":
    unittest.main()

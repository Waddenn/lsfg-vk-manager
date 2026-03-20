from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from .constants import LOSSLESS_DLL
from .models import Game, Profile
from .utils import escape_toml, normalize_exec


def game_matches_profile(game: Game, profile: Profile) -> bool:
    wanted = {normalize_exec(entry) for entry in game.executables}
    actual = {normalize_exec(entry) for entry in profile.active_in}
    return bool(wanted & actual)


def game_fields_match_profile(game: Game, profile: Profile) -> bool:
    return (
        [normalize_exec(entry) for entry in game.executables] == [normalize_exec(entry) for entry in profile.active_in]
        and (game.profile_name or f"{game.name} 2x FG") == profile.name
        and game.multiplier == profile.multiplier
        and round(game.flow_scale, 2) == round(profile.flow_scale, 2)
        and game.performance_mode is profile.performance_mode
        and game.pacing == profile.pacing
        and (game.gpu or "") == (profile.gpu or "")
    )


class ConfigStore:
    def __init__(self, path: Path, default_dll: Path | str | None = None) -> None:
        self.path = path
        self.version = 2
        self.default_dll = str(default_dll or LOSSLESS_DLL)
        self.global_conf: dict[str, Any] = {
            "allow_fp16": True,
            "dll": self.default_dll,
        }
        self.profiles: list[Profile] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.write()
            return

        try:
            data = tomllib.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            self.global_conf = {
                "allow_fp16": True,
                "dll": self.default_dll,
            }
            self.profiles = []
            return
        self.version = int(data.get("version", 2))
        global_conf = data.get("global", {})
        self.global_conf = {
            "allow_fp16": bool(global_conf.get("allow_fp16", True)),
            "dll": str(global_conf.get("dll", self.default_dll)),
        }

        self.profiles = []
        for raw in data.get("profile", []):
            active = raw.get("active_in", [])
            if isinstance(active, str):
                active = [active]
            self.profiles.append(
                Profile(
                    name=str(raw.get("name", "Unnamed profile")),
                    active_in=[str(entry) for entry in active],
                    multiplier=int(raw.get("multiplier", 2)),
                    flow_scale=float(raw.get("flow_scale", 1.0)),
                    performance_mode=bool(raw.get("performance_mode", False)),
                    pacing=str(raw.get("pacing", "none")),
                    gpu=str(raw["gpu"]) if "gpu" in raw else None,
                    managed_appid=str(raw.get("managed_appid")) if raw.get("managed_appid") else None,
                )
            )

    def save_games(self, games: list[Game]) -> None:
        unmanaged = [profile for profile in self.profiles if not profile.managed_appid]

        managed: list[Profile] = []
        for game in games:
            if not game.enabled:
                continue
            active = game.executables[:]
            if not active:
                continue
            if (
                game.matched_profile
                and not game.matched_profile.managed_appid
                and game_fields_match_profile(game, game.matched_profile)
            ):
                continue
            managed.append(
                Profile(
                    name=game.profile_name or f"{game.name} 2x FG",
                    active_in=active,
                    multiplier=game.multiplier,
                    flow_scale=round(game.flow_scale, 2),
                    performance_mode=game.performance_mode,
                    pacing=game.pacing,
                    gpu=game.gpu,
                    managed_appid=game.appid,
                )
            )

        self.profiles = unmanaged + managed
        self.write()

    def write(self) -> None:
        def flow_value(value: float) -> str:
            text = f"{value:.2f}"
            return text.rstrip("0").rstrip(".")

        lines: list[str] = [
            "version = 2",
            "",
            "[global]",
            f"allow_fp16 = {'true' if self.global_conf.get('allow_fp16', True) else 'false'}",
            f'dll = "{escape_toml(str(self.global_conf.get("dll", self.default_dll)))}"',
        ]

        for profile in self.profiles:
            lines.extend(
                [
                    "",
                    "[[profile]]",
                    f'name = "{escape_toml(profile.name)}"',
                    "active_in = [",
                ]
            )
            for entry in profile.active_in:
                lines.append(f'    "{escape_toml(entry)}",')
            lines.extend(
                [
                    "]",
                    f"multiplier = {profile.multiplier}",
                    f"flow_scale = {flow_value(profile.flow_scale)}",
                    f"performance_mode = {'true' if profile.performance_mode else 'false'}",
                    f'pacing = "{escape_toml(profile.pacing)}"',
                ]
            )
            if profile.gpu:
                lines.append(f'gpu = "{escape_toml(profile.gpu)}"')
            if profile.managed_appid:
                lines.append(f'managed_appid = "{escape_toml(profile.managed_appid)}"')

        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

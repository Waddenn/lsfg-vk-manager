from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

from .constants import LOSSLESS_DLL
from .models import Game, Profile
from .settings import ManagedProfileMetadata
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
    )


class ConfigStore:
    def __init__(
        self,
        path: Path,
        default_dll: Path | str | None = None,
        managed_metadata: dict[str, ManagedProfileMetadata] | None = None,
    ) -> None:
        self.path = path
        self.version = 1
        self.default_dll = str(default_dll or LOSSLESS_DLL)
        self.global_conf: dict[str, Any] = {
            "allow_fp16": True,
            "dll": self.default_dll,
        }
        self.profiles: list[Profile] = []
        self.managed_metadata = managed_metadata if managed_metadata is not None else {}
        self.load()

    @staticmethod
    def _flow_value(value: float) -> str:
        text = f"{value:.2f}"
        return text.rstrip("0").rstrip(".")

    @staticmethod
    def _parse_legacy_v1_manager_metadata(text: str) -> list[dict[str, str]]:
        blocks: list[dict[str, str]] = []
        pending: dict[str, str] = {}
        pattern = re.compile(r'^#\s*lsfg-vk-manager\s+([a-z_]+)\s*=\s*"(.*)"\s*$')

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                pending = {}
                continue
            match = pattern.match(line)
            if match:
                key, value = match.groups()
                pending[key] = value.replace('\\"', '"').replace("\\\\", "\\")
                continue
            if line == "[[game]]":
                blocks.append(pending.copy())
                pending = {}
                continue
            if not line.startswith("#"):
                pending = {}

        return blocks

    def _load_v1(self, data: dict[str, Any], text: str) -> None:
        self.global_conf = {
            "allow_fp16": not bool(data.get("no_fp16", False)),
            "dll": str(data.get("dll", self.default_dll)),
        }

        self.profiles = []
        legacy_metadata = self._parse_legacy_v1_manager_metadata(text)
        for index, raw in enumerate(data.get("game", [])):
            exe = str(raw.get("exe", "")).strip()
            if not exe:
                continue

            matched_appid: str | None = None
            matched_metadata: ManagedProfileMetadata | None = None
            normalized_exe = normalize_exec(exe)

            legacy = legacy_metadata[index] if index < len(legacy_metadata) else {}
            legacy_appid = legacy.get("managed_appid")
            if legacy_appid and legacy_appid not in self.managed_metadata:
                self.managed_metadata[legacy_appid] = ManagedProfileMetadata(
                    name=legacy.get("name", ""),
                    executables=[exe],
                    gpu=legacy.get("gpu", ""),
                    pacing=legacy.get("pacing", "none"),
                )

            for appid, metadata in self.managed_metadata.items():
                normalized_entries = {normalize_exec(entry) for entry in metadata.executables}
                if normalized_exe in normalized_entries:
                    matched_appid = appid
                    matched_metadata = metadata
                    break

            self.profiles.append(
                Profile(
                    name=(matched_metadata.name if matched_metadata and matched_metadata.name else exe),
                    active_in=[exe],
                    multiplier=int(raw.get("multiplier", 2)),
                    flow_scale=float(raw.get("flow_scale", 1.0)),
                    performance_mode=bool(raw.get("performance_mode", False)),
                    hdr_mode=bool(raw.get("hdr_mode", False)),
                    experimental_present_mode=str(raw.get("experimental_present_mode"))
                    if raw.get("experimental_present_mode")
                    else None,
                    pacing=matched_metadata.pacing if matched_metadata else "none",
                    gpu=matched_metadata.gpu if matched_metadata and matched_metadata.gpu else None,
                    managed_appid=matched_appid,
                )
            )

    def _load_v2(self, data: dict[str, Any]) -> None:
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
                    hdr_mode=bool(raw.get("hdr_mode", False)),
                    experimental_present_mode=str(raw.get("experimental_present_mode"))
                    if raw.get("experimental_present_mode")
                    else None,
                    pacing=str(raw.get("pacing", "none")),
                    gpu=str(raw["gpu"]) if "gpu" in raw else None,
                    managed_appid=str(raw.get("managed_appid")) if raw.get("managed_appid") else None,
                )
            )

    def load(self) -> None:
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.write()
            return

        try:
            text = self.path.read_text(encoding="utf-8")
            data = tomllib.loads(text)
        except (OSError, tomllib.TOMLDecodeError):
            self.global_conf = {
                "allow_fp16": True,
                "dll": self.default_dll,
            }
            self.profiles = []
            return

        self.version = int(data.get("version", 1))
        if self.version == 1:
            self._load_v1(data, text)
        else:
            self._load_v2(data)

    def save_games(self, games: list[Game]) -> None:
        unmanaged = [profile for profile in self.profiles if not profile.managed_appid]

        managed: list[Profile] = []
        next_managed_metadata: dict[str, ManagedProfileMetadata] = {
            appid: metadata
            for appid, metadata in self.managed_metadata.items()
            if appid not in {game.appid for game in games}
        }

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
            next_managed_metadata[game.appid] = ManagedProfileMetadata(
                name=game.profile_name or f"{game.name} 2x FG",
                executables=active,
                gpu=game.gpu,
                pacing=game.pacing,
            )

        self.managed_metadata.clear()
        self.managed_metadata.update(next_managed_metadata)

        self.profiles = unmanaged + managed
        self.write()

    def _write_v1(self) -> None:
        lines: list[str] = [
            "version = 1",
            f'dll = "{escape_toml(str(self.global_conf.get("dll", self.default_dll)))}"',
        ]
        if not self.global_conf.get("allow_fp16", True):
            lines.append("no_fp16 = true")

        for profile in self.profiles:
            for entry in profile.active_in:
                lines.extend(
                    [
                        "",
                        "[[game]]",
                        f'exe = "{escape_toml(entry)}"',
                        f"multiplier = {profile.multiplier}",
                        f"flow_scale = {self._flow_value(profile.flow_scale)}",
                        f"performance_mode = {'true' if profile.performance_mode else 'false'}",
                        f"hdr_mode = {'true' if profile.hdr_mode else 'false'}",
                    ]
                )
                if profile.experimental_present_mode:
                    lines.append(
                        f'experimental_present_mode = "{escape_toml(profile.experimental_present_mode)}"'
                    )

        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _write_v2(self) -> None:
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
                    f"flow_scale = {self._flow_value(profile.flow_scale)}",
                    f"performance_mode = {'true' if profile.performance_mode else 'false'}",
                    f"hdr_mode = {'true' if profile.hdr_mode else 'false'}",
                    f'pacing = "{escape_toml(profile.pacing)}"',
                ]
            )
            if profile.experimental_present_mode:
                lines.append(
                    f'experimental_present_mode = "{escape_toml(profile.experimental_present_mode)}"'
                )
            if profile.gpu:
                lines.append(f'gpu = "{escape_toml(profile.gpu)}"')
            if profile.managed_appid:
                lines.append(f'managed_appid = "{escape_toml(profile.managed_appid)}"')

        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def write(self) -> None:
        if self.version == 1:
            self._write_v1()
            return
        self._write_v2()

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from .constants import (
    APP_SETTINGS_PATH,
    HYTALE_RELEASE,
    LSFG_CONFIG,
    STEAM_APPS,
    STEAM_COMMON,
)
from .gpu import detect_default_gpu
from .utils import escape_toml


@dataclass
class SourceSettings:
    steam_apps: str = str(STEAM_APPS)
    steam_common: str = str(STEAM_COMMON)
    hytale_release: str = str(HYTALE_RELEASE)
    lsfg_config: str = str(LSFG_CONFIG)
    default_gpu: str = ""

    @property
    def steam_apps_path(self) -> Path:
        return Path(self.steam_apps).expanduser()

    @property
    def steam_common_path(self) -> Path:
        return Path(self.steam_common).expanduser()

    @property
    def hytale_release_path(self) -> Path:
        return Path(self.hytale_release).expanduser()

    @property
    def lsfg_config_path(self) -> Path:
        return Path(self.lsfg_config).expanduser()

    @property
    def steam_appinfo_path(self) -> Path:
        return self.steam_apps_path.parent / "appcache/appinfo.vdf"

    @property
    def lossless_dll_path(self) -> Path:
        return self.steam_common_path / "Lossless Scaling/Lossless.dll"


class SettingsStore:
    def __init__(self, path: Path = APP_SETTINGS_PATH) -> None:
        self.path = path
        self.sources = SourceSettings(default_gpu=detect_default_gpu())
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.write()
            return

        detected_gpu = detect_default_gpu()
        try:
            data = tomllib.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            self.sources = SourceSettings(default_gpu=detected_gpu)
            return
        sources = data.get("sources", {})
        self.sources = SourceSettings(
            steam_apps=str(sources.get("steam_apps", STEAM_APPS)),
            steam_common=str(sources.get("steam_common", STEAM_COMMON)),
            hytale_release=str(sources.get("hytale_release", HYTALE_RELEASE)),
            lsfg_config=str(sources.get("lsfg_config", LSFG_CONFIG)),
            default_gpu=str(sources.get("default_gpu", detected_gpu)),
        )

    def write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "[sources]",
            f'steam_apps = "{escape_toml(self.sources.steam_apps)}"',
            f'steam_common = "{escape_toml(self.sources.steam_common)}"',
            f'hytale_release = "{escape_toml(self.sources.hytale_release)}"',
            f'lsfg_config = "{escape_toml(self.sources.lsfg_config)}"',
            f'default_gpu = "{escape_toml(self.sources.default_gpu)}"',
            "",
        ]
        self.path.write_text("\n".join(lines), encoding="utf-8")


def validate_sources(sources: SourceSettings) -> list[str]:
    issues: list[str] = []

    directory_fields = (
        ("Steam steamapps", sources.steam_apps_path),
        ("Steam common", sources.steam_common_path),
    )
    for label, path in directory_fields:
        if path.exists() and not path.is_dir():
            issues.append(f"{label}: expected a directory")

    hytale_path = sources.hytale_release_path
    if hytale_path.exists() and not hytale_path.is_dir():
        issues.append("Hytale release: expected a directory")

    config_path = sources.lsfg_config_path
    if config_path.exists() and not config_path.is_file():
        issues.append("lsfg-vk conf.toml: expected a file")

    if not sources.default_gpu.strip():
        issues.append("Default GPU: value cannot be empty")

    return issues


def inspect_source_warnings(sources: SourceSettings) -> list[str]:
    warnings: list[str] = []

    directory_fields = (
        ("Steam steamapps", sources.steam_apps_path),
        ("Steam common", sources.steam_common_path),
        ("Hytale release", sources.hytale_release_path),
    )
    for label, path in directory_fields:
        if not path.exists():
            warnings.append(f"{label}: path does not exist")

    config_path = sources.lsfg_config_path
    if not config_path.exists() and not config_path.parent.exists():
        warnings.append("lsfg-vk conf.toml: parent directory does not exist")

    return warnings

from __future__ import annotations

import json
import re
from pathlib import Path

from .appinfo import get_install_valid_launch_executables
from .config_store import ConfigStore, game_matches_profile
from .discovery import discover_executables
from .gpu import GPU_FALLBACK_NAME
from .models import Game
from .settings import SourceSettings
from .utils import parse_acf


def should_skip_steam_app(name: str, installdir: str) -> bool:
    lower_name = name.lower()
    lower_dir = installdir.lower()

    if lower_name.startswith("proton ") or lower_name == "proton experimental":
        return True
    if lower_name.startswith("steam linux runtime"):
        return True
    if lower_name == "steamworks common redistributables":
        return True
    if lower_dir.startswith("proton"):
        return True
    if lower_dir.startswith("steamlinuxruntime_"):
        return True

    return False


def _read_ryujinx_game_dirs(config_path: Path) -> list[Path]:
    if not config_path.exists():
        return []
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    result: list[Path] = []
    for entry in data.get("game_dirs", []):
        path = Path(str(entry)).expanduser()
        if path.exists() and path.is_dir():
            result.append(path)
    return result


def _clean_ryujinx_name(raw: str) -> str:
    name = Path(raw).stem
    name = re.sub(r"\[[^\]]+\]", "", name)
    name = re.sub(r"\([^)]*\)", "", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip(" -_[]()") or raw


def _slugify_ryujinx_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "game"


def _make_ryujinx_process_name(title_id: str, name: str) -> str:
    return f"ryujinx-{_slugify_ryujinx_name(name)}-{title_id.lower()}"


def _find_ryujinx_content_path(game_dirs: list[Path], title_id: str) -> Path | None:
    candidates: list[Path] = []
    for game_dir in game_dirs:
        for path in game_dir.rglob("*"):
            haystack = str(path)
            if title_id in haystack or f"[{title_id}]" in haystack:
                candidates.append(path)

    files = [path for path in candidates if path.is_file()]
    if files:
        files.sort(key=lambda path: (path.suffix.lower() not in {".xci", ".nsp"}, len(str(path))))
        return files[0]

    dirs = [path for path in candidates if path.is_dir()]
    if dirs:
        dirs.sort(key=lambda path: len(str(path)))
        return dirs[0]
    return None


def _discover_ryujinx_games(sources: SourceSettings) -> list[Game]:
    config_path = sources.ryujinx_config_path
    game_dirs = _read_ryujinx_game_dirs(config_path)
    games_root = config_path.parent / "games"
    if not games_root.exists():
        return []

    games: list[Game] = []
    for entry in sorted(games_root.iterdir()):
        if not entry.is_dir():
            continue
        title_id = entry.name.upper()
        if not re.fullmatch(r"[0-9A-Fa-f]{16}", title_id):
            continue

        content_path = _find_ryujinx_content_path(game_dirs, title_id) or entry
        derived_name = _clean_ryujinx_name(content_path.name)
        process_name = _make_ryujinx_process_name(title_id, derived_name)
        games.append(
            Game(
                appid=f"custom:ryujinx:{title_id}",
                name=f"{derived_name} [Ryujinx]",
                installdir=title_id,
                install_path=content_path,
                executables=[process_name],
                detected_executables=[process_name],
                profile_name=f"{derived_name} 2x FG",
            )
        )

    return games


def load_games(config: ConfigStore, sources: SourceSettings) -> list[Game]:
    games: list[Game] = []
    steam_apps = sources.steam_apps_path
    steam_common = sources.steam_common_path
    hytale_release = sources.hytale_release_path

    if steam_apps.exists():
        manifests = sorted(steam_apps.glob("appmanifest_*.acf"))
        for manifest in manifests:
            data = parse_acf(manifest)
            appid = data.get("appid")
            name = data.get("name")
            installdir = data.get("installdir")
            if not (appid and name and installdir):
                continue
            if should_skip_steam_app(name, installdir):
                continue

            install_path = steam_common / installdir
            launch_executables = get_install_valid_launch_executables(
                sources.steam_appinfo_path,
                appid,
                install_path,
            )
            detected_executables = launch_executables or discover_executables(install_path, name)
            games.append(
                Game(
                    appid=appid,
                    name=name,
                    installdir=installdir,
                    install_path=install_path,
                    executables=detected_executables[:],
                    detected_executables=detected_executables,
                    profile_name=f"{name} 2x FG",
                )
            )

    hytale_client = hytale_release / "Client/HytaleClient"
    if hytale_client.exists():
        hytale_executables = discover_executables(hytale_release, "Hytale")
        if "Client/HytaleClient" not in hytale_executables:
            hytale_executables.insert(0, "Client/HytaleClient")
        if "HytaleClient" not in hytale_executables:
            hytale_executables.insert(1, "HytaleClient")

        games.append(
            Game(
                appid="custom:hytale",
                name="Hytale",
                installdir="Hytale",
                install_path=hytale_release,
                executables=hytale_executables,
                detected_executables=hytale_executables[:],
                profile_name="Hytale 2x FG",
            )
        )

    games.extend(_discover_ryujinx_games(sources))

    for game in games:
        for profile in config.profiles:
            if profile.managed_appid == game.appid or game_matches_profile(game, profile):
                game.enabled = True
                game.profile_name = profile.name
                game.multiplier = profile.multiplier
                game.flow_scale = profile.flow_scale
                game.performance_mode = profile.performance_mode
                game.pacing = profile.pacing
                game.gpu = profile.gpu or sources.default_gpu or GPU_FALLBACK_NAME
                game.matched_profile_name = profile.name
                game.matched_profile = profile
                game.profile_source = "managed" if profile.managed_appid == game.appid else "existing"
                break

    games.sort(key=lambda item: (not item.enabled, item.name.lower()))
    return games

from __future__ import annotations

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
            detected_executables = discover_executables(install_path, name)
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
                break

    games.sort(key=lambda item: (not item.enabled, item.name.lower()))
    return games

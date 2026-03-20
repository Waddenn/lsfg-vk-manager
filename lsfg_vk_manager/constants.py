from __future__ import annotations

from pathlib import Path


STEAM_ROOT = Path.home() / ".local/share/Steam"
STEAM_APPS = STEAM_ROOT / "steamapps"
STEAM_COMMON = STEAM_APPS / "common"
LSFG_CONFIG = Path.home() / ".config/lsfg-vk/conf.toml"
LOSSLESS_DLL = STEAM_COMMON / "Lossless Scaling/Lossless.dll"
HYTALE_ROOT = Path.home() / ".local/share/Hytale"
HYTALE_RELEASE = HYTALE_ROOT / "install/release/package/game/latest"
APP_ID = "org.tom.lsfgvkmanager"
APP_SETTINGS_PATH = Path.home() / ".config/lsfg-vk-manager/settings.toml"

EXECUTABLE_SUFFIXES = {
    ".exe",
    ".x64",
    ".x86_64",
    ".sh",
    ".appimage",
}

SKIP_EXEC_NAMES = {
    "vc_redist.x64.exe",
    "vc_redist.x86.exe",
    "unins000.exe",
    "support.exe",
    "crashsender.exe",
    "unitycrashhandler64.exe",
    "unitycrashhandler32.exe",
    "start_protected_game.exe",
    "eac_launcher.exe",
    "eadesktop.exe",
    "perf_graph_viewer.exe",
}

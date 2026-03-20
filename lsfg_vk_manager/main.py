from __future__ import annotations

import sys

from .config_store import ConfigStore
from .library import load_games
from .settings import SettingsStore


def main() -> None:
    settings = SettingsStore()
    sources = settings.sources

    if len(sys.argv) > 1 and sys.argv[1] == "--smoke-test":
        config = ConfigStore(sources.lsfg_config_path, default_dll=sources.lossless_dll_path)
        games = load_games(config, sources)
        print(f"games={len(games)} enabled={sum(1 for game in games if game.enabled)}")
        if games:
            print(f"first={games[0].name}")
        return

    from .ui import run_app

    run_app()


if __name__ == "__main__":
    main()

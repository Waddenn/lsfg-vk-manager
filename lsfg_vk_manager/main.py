from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import TextIO

from .config_store import ConfigStore
from .library import load_games
from .settings import SettingsStore
from .utils import format_error_message


def _print_startup_error(exc: Exception, stderr: TextIO) -> int:
    stderr.write(f"Startup failed: {format_error_message(exc)}\n")
    return 1


def main(argv: Sequence[str] | None = None, stderr: TextIO | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    stderr = stderr or sys.stderr

    try:
        settings = SettingsStore()
        sources = settings.sources
    except Exception as exc:
        return _print_startup_error(exc, stderr)

    if argv and argv[0] == "--smoke-test":
        try:
            config = ConfigStore(
                sources.lsfg_config_path,
                default_dll=sources.lossless_dll_path,
                managed_metadata=settings.managed_profiles,
            )
            games = load_games(config, sources)
        except Exception as exc:
            return _print_startup_error(exc, stderr)
        print(f"games={len(games)} enabled={sum(1 for game in games if game.enabled)}")
        if games:
            print(f"first={games[0].name}")
        return 0

    try:
        from .ui import run_app

        run_app()
    except Exception as exc:
        return _print_startup_error(exc, stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

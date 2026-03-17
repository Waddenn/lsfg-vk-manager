# LSFG Game Manager

Small native GTK/libadwaita desktop app for managing `lsfg-vk` profiles per Steam game on Linux.

## Screenshot

![LSFG Game Manager screenshot](screenshots/main-window.png)

## What It Does

- Scans installed Steam games from `~/.local/share/Steam/steamapps`
- Detects likely executables from each game install
- Lets you enable or disable `lsfg-vk` per game
- Edits `~/.config/lsfg-vk/conf.toml` directly
- Preserves unmanaged profiles and writes managed ones cleanly

## Run

```bash
./app.py
```

You can also run it with Python explicitly:

```bash
python app.py
```

## Smoke Test

```bash
python app.py --smoke-test
```

## Notes

- The app currently targets the local Steam install under `~/.local/share/Steam`.

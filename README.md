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

Or through the installed wrapper:

```bash
lsfg-vk-manager
```

## Smoke Test

```bash
lsfg-vk-manager --smoke-test
```

## Notes

- The wrapper exports `DISABLE_LSFGVK=1` so the manager itself is not injected by `lsfg-vk`.
- The app currently targets the local Steam install under `~/.local/share/Steam`.

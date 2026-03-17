#!/usr/bin/env python3

from __future__ import annotations

import os
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GObject, Gtk  # noqa: E402


STEAM_ROOT = Path.home() / ".local/share/Steam"
STEAM_APPS = STEAM_ROOT / "steamapps"
STEAM_COMMON = STEAM_APPS / "common"
LSFG_CONFIG = Path.home() / ".config/lsfg-vk/conf.toml"
LOSSLESS_DLL = STEAM_COMMON / "Lossless Scaling/Lossless.dll"
GPU_NAME = "AMD Radeon 860M Graphics (RADV KRACKAN1)"
APP_ID = "org.tom.lsfgvkmanager"

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


@dataclass
class Profile:
    name: str
    active_in: list[str]
    multiplier: int = 2
    flow_scale: float = 1.0
    performance_mode: bool = False
    pacing: str = "none"
    gpu: str | None = None
    managed_appid: str | None = None


@dataclass
class Game:
    appid: str
    name: str
    installdir: str
    install_path: Path
    executables: list[str]
    enabled: bool = False
    profile_name: str = ""
    multiplier: int = 2
    flow_scale: float = 1.0
    performance_mode: bool = False
    pacing: str = "none"
    gpu: str = GPU_NAME
    matched_profile_name: str | None = None


def parse_acf(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    pairs = re.findall(r'"([^"]+)"\s+"([^"]*)"', text)
    return {key: value for key, value in pairs}


def normalize_exec(value: str) -> str:
    return value.strip().replace("\\", "/").lower()


def is_candidate_executable(path: Path) -> bool:
    if not path.is_file():
        return False

    lower = path.name.lower()
    if lower in SKIP_EXEC_NAMES:
        return False

    if path.suffix.lower() in EXECUTABLE_SUFFIXES:
        return True

    try:
        return os.access(path, os.X_OK)
    except OSError:
        return False


def score_executable(path: Path, game_name: str) -> tuple[int, str]:
    rel = str(path).replace("\\", "/").lower()
    name = path.name.lower()
    base = game_name.lower().replace(":", "").replace("-", "").replace(" ", "")
    score = 0

    if "bin64" in rel or "binlinux" in rel:
        score += 25
    if name.endswith(".exe"):
        score += 20
    if base and base in name.replace(".", "").replace("_", "").replace("-", ""):
        score += 40
    if "demo" in rel and "demo" in base:
        score += 10
    if any(token in name for token in ("launcher", "crash", "support", "eac")):
        score -= 50

    return score, rel


def discover_executables(install_path: Path, game_name: str) -> list[str]:
    if not install_path.exists():
        return []

    candidates: list[Path] = []
    for root, dirs, files in os.walk(install_path):
        rel_depth = len(Path(root).relative_to(install_path).parts)
        if rel_depth > 4:
            dirs[:] = []
            continue
        for filename in files:
            path = Path(root) / filename
            if is_candidate_executable(path):
                candidates.append(path)

    scored = sorted(
        ((score_executable(path.relative_to(install_path), game_name), path.relative_to(install_path)) for path in candidates),
        reverse=True,
    )

    seen: set[str] = set()
    chosen: list[str] = []
    for (_, _), rel_path in scored:
        normalized = normalize_exec(str(rel_path))
        basename = normalize_exec(rel_path.name)
        for candidate in (str(rel_path).replace("\\", "/"), rel_path.name):
            if normalize_exec(candidate) in seen:
                continue
            chosen.append(candidate.replace("\\", "/"))
            seen.add(normalize_exec(candidate))
        seen.add(normalized)
        seen.add(basename)
        if len(chosen) >= 8:
            break

    return chosen


class ConfigStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.version = 2
        self.global_conf: dict[str, Any] = {
            "allow_fp16": True,
            "dll": str(LOSSLESS_DLL),
        }
        self.profiles: list[Profile] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.write()
            return

        data = tomllib.loads(self.path.read_text(encoding="utf-8"))
        self.version = int(data.get("version", 2))
        global_conf = data.get("global", {})
        self.global_conf = {
            "allow_fp16": bool(global_conf.get("allow_fp16", True)),
            "dll": str(global_conf.get("dll", LOSSLESS_DLL)),
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
        unmanaged: list[Profile] = []
        for profile in self.profiles:
            should_skip = bool(profile.managed_appid)
            if not should_skip:
                for game in games:
                    if game.enabled and game_matches_profile(game, profile):
                        should_skip = True
                        break
            if should_skip:
                continue
            unmanaged.append(profile)

        managed: list[Profile] = []
        for game in games:
            if not game.enabled:
                continue
            active = game.executables[:]
            if not active:
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
            f'dll = "{self.global_conf.get("dll", str(LOSSLESS_DLL))}"',
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


def escape_toml(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def game_matches_profile(game: Game, profile: Profile) -> bool:
    wanted = {normalize_exec(entry) for entry in game.executables}
    actual = {normalize_exec(entry) for entry in profile.active_in}
    return bool(wanted & actual)


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


def load_games(config: ConfigStore) -> list[Game]:
    games: list[Game] = []
    if not STEAM_APPS.exists():
        return games

    manifests = sorted(STEAM_APPS.glob("appmanifest_*.acf"))
    for manifest in manifests:
        data = parse_acf(manifest)
        appid = data.get("appid")
        name = data.get("name")
        installdir = data.get("installdir")
        if not (appid and name and installdir):
            continue
        if should_skip_steam_app(name, installdir):
            continue

        install_path = STEAM_COMMON / installdir
        executables = discover_executables(install_path, name)
        game = Game(
            appid=appid,
            name=name,
            installdir=installdir,
            install_path=install_path,
            executables=executables,
            profile_name=f"{name} 2x FG",
        )

        for profile in config.profiles:
            if profile.managed_appid == appid or game_matches_profile(game, profile):
                game.enabled = True
                game.profile_name = profile.name
                game.multiplier = profile.multiplier
                game.flow_scale = profile.flow_scale
                game.performance_mode = profile.performance_mode
                game.pacing = profile.pacing
                game.gpu = profile.gpu or GPU_NAME
                game.matched_profile_name = profile.name
                break

        games.append(game)

    games.sort(key=lambda item: (not item.enabled, item.name.lower()))
    return games


class GameRow(Gtk.ListBoxRow):
    def __init__(self, game: Game) -> None:
        super().__init__()
        self.game = game
        self.set_selectable(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        box.set_margin_start(12)
        box.set_margin_end(12)

        title = Gtk.Label(xalign=0)
        title.add_css_class("title-4")
        title.set_label(game.name)

        subtitle = Gtk.Label(xalign=0)
        subtitle.add_css_class("dim-label")
        subtitle.set_label(self._subtitle())

        box.append(title)
        box.append(subtitle)
        self.set_child(box)

    def refresh(self) -> None:
        child = self.get_child()
        if isinstance(child, Gtk.Box):
            subtitle = child.get_last_child()
            if isinstance(subtitle, Gtk.Label):
                subtitle.set_label(self._subtitle())

    def _subtitle(self) -> str:
        state = "Active" if self.game.enabled else "Inactive"
        execs = len(self.game.executables)
        return f"{state} • {execs} executable{'s' if execs != 1 else ''} detected"


class LsfgManagerWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, title="LSFG Game Manager")
        self.set_default_size(1180, 760)

        self.config = ConfigStore(LSFG_CONFIG)
        self.games = load_games(self.config)
        self.filtered_games = self.games[:]
        self.current_game: Game | None = None
        self.row_map: dict[str, GameRow] = {}
        self.block_updates = False
        self.autosave_source_id: int | None = None

        self._build_ui()
        self._reload_list()
        if self.filtered_games:
            self._select_game(self.filtered_games[0])

    def _build_ui(self) -> None:
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        toolbar = Adw.ToolbarView()
        toolbar.set_top_bar_style(Adw.ToolbarStyle.RAISED)
        self.toast_overlay.set_child(toolbar)

        header = Adw.HeaderBar()
        header.set_title_widget(Gtk.Label(label="LSFG Game Manager"))

        reload_button = Gtk.Button(label="Reload")
        reload_button.add_css_class("flat")
        reload_button.set_tooltip_text("Rescan installed Steam games")
        reload_button.connect("clicked", self._on_reload_clicked)
        header.pack_start(reload_button)

        toolbar.add_top_bar(header)

        split = Adw.NavigationSplitView.new()
        split.set_min_sidebar_width(280)
        split.set_max_sidebar_width(360)
        split.set_sidebar_width_fraction(0.28)
        split.set_sidebar_width_unit(Adw.LengthUnit.PX)
        split.set_sidebar(Adw.NavigationPage.new(self._build_sidebar(), "Games"))
        split.set_content(Adw.NavigationPage.new(self._build_content(), "Details"))
        split.set_show_content(True)
        self.split_view = split
        toolbar.set_content(split)

        css = Gtk.CssProvider()
        css.load_from_data(
            b"""
            .game-card {
                background: alpha(@window_fg_color, 0.035);
                border-radius: 18px;
                padding: 18px;
            }
            .stat-chip {
                background: alpha(@accent_bg_color, 0.14);
                border-radius: 999px;
                padding: 6px 10px;
            }
            .mono-block {
                font-family: monospace;
            }
            """
        )
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _build_sidebar(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(14)
        box.set_margin_bottom(14)
        box.set_margin_start(14)
        box.set_margin_end(14)
        box.set_hexpand(True)
        box.set_vexpand(True)

        search = Gtk.SearchEntry()
        search.set_placeholder_text("Search installed Steam games")
        search.set_hexpand(True)
        search.connect("search-changed", self._on_search_changed)
        self.search_entry = search

        summary = Gtk.Label(xalign=0)
        summary.add_css_class("dim-label")
        self.summary_label = summary

        self.game_list = Gtk.ListBox()
        self.game_list.add_css_class("navigation-sidebar")
        self.game_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.game_list.set_hexpand(True)
        self.game_list.set_vexpand(True)
        self.game_list.connect("row-selected", self._on_row_selected)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.set_hexpand(True)
        scroll.set_child(self.game_list)

        box.append(search)
        box.append(summary)
        box.append(scroll)
        return box

    def _build_content(self) -> Gtk.Widget:
        clamp = Adw.Clamp(maximum_size=860)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_hexpand(True)
        scroll.set_vexpand(True)
        clamp.set_child(scroll)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        outer.set_margin_top(22)
        outer.set_margin_bottom(22)
        outer.set_margin_start(22)
        outer.set_margin_end(22)
        scroll.set_child(outer)

        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        hero.add_css_class("game-card")

        self.title_label = Gtk.Label(xalign=0)
        self.title_label.add_css_class("title-1")
        self.title_label.set_wrap(True)

        self.path_label = Gtk.Label(xalign=0)
        self.path_label.add_css_class("dim-label")
        self.path_label.set_wrap(True)

        self.meta_label = Gtk.Label(xalign=0)
        self.meta_label.add_css_class("dim-label")
        self.meta_label.set_wrap(True)

        hero.append(self.title_label)
        hero.append(self.path_label)
        hero.append(self.meta_label)
        outer.append(hero)

        toggles_group = Adw.PreferencesGroup(title="Profile")
        outer.append(toggles_group)

        self.enabled_row = Adw.SwitchRow(title="Enable lsfg-vk for this game")
        self.enabled_row.set_subtitle("Writes or removes a managed profile in conf.toml")
        self.enabled_row.connect("notify::active", self._on_enabled_toggled)
        toggles_group.add(self.enabled_row)

        self.profile_name_row = Adw.EntryRow(title="Profile name")
        self.profile_name_row.connect("notify::text", self._on_profile_field_changed)
        toggles_group.add(self.profile_name_row)

        tuning_group = Adw.PreferencesGroup(title="Frame Generation")
        outer.append(tuning_group)

        self.multiplier_row = Adw.SpinRow.new_with_range(2, 4, 1)
        self.multiplier_row.set_title("Multiplier")
        self.multiplier_row.set_subtitle("2x is the safest baseline")
        self.multiplier_row.connect("notify::value", self._on_profile_field_changed)
        tuning_group.add(self.multiplier_row)

        self.flow_row = Adw.ActionRow(title="Flow scale", subtitle="Lower is faster, higher is cleaner")
        self.flow_adjustment = Gtk.Adjustment(value=1.0, lower=0.25, upper=1.0, step_increment=0.05, page_increment=0.1)
        self.flow_scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=self.flow_adjustment, digits=2, hexpand=True)
        self.flow_scale.set_draw_value(True)
        self.flow_scale.connect("value-changed", self._on_profile_field_changed)
        self.flow_row.add_suffix(self.flow_scale)
        tuning_group.add(self.flow_row)

        self.performance_row = Adw.SwitchRow(title="Performance mode")
        self.performance_row.set_subtitle("Lighter FG model with a small quality tradeoff")
        self.performance_row.connect("notify::active", self._on_profile_field_changed)
        tuning_group.add(self.performance_row)

        advanced_group = Adw.PreferencesGroup(title="Advanced")
        outer.append(advanced_group)

        self.pacing_row = Adw.ComboRow(title="Pacing")
        self.pacing_model = Gtk.StringList.new(["none"])
        self.pacing_row.set_model(self.pacing_model)
        self.pacing_row.set_selected(0)
        self.pacing_row.connect("notify::selected", self._on_profile_field_changed)
        advanced_group.add(self.pacing_row)

        self.gpu_row = Adw.EntryRow(title="GPU")
        self.gpu_row.connect("notify::text", self._on_profile_field_changed)
        advanced_group.add(self.gpu_row)

        exec_header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        exec_title = Gtk.Label(xalign=0, label="Detected executables")
        exec_title.add_css_class("title-4")
        exec_subtitle = Gtk.Label(
            xalign=0,
            label="Auto-detected from the Steam install folder. These are written to active_in.",
        )
        exec_subtitle.add_css_class("dim-label")
        exec_subtitle.set_wrap(True)
        exec_header.append(exec_title)
        exec_header.append(exec_subtitle)
        outer.append(exec_header)

        exec_frame = Gtk.Frame()
        self.execs_label = Gtk.Label(xalign=0)
        self.execs_label.add_css_class("mono-block")
        self.execs_label.set_wrap(True)
        self.execs_label.set_selectable(True)
        self.execs_label.set_margin_top(12)
        self.execs_label.set_margin_bottom(12)
        self.execs_label.set_margin_start(12)
        self.execs_label.set_margin_end(12)
        exec_frame.set_child(self.execs_label)
        outer.append(exec_frame)

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        footer.set_margin_top(6)
        self.status_label = Gtk.Label(xalign=0)
        self.status_label.set_hexpand(True)
        self.status_label.add_css_class("dim-label")
        footer.append(self.status_label)
        outer.append(footer)

        return clamp

    def _reload_list(self) -> None:
        while True:
            row = self.game_list.get_first_child()
            if row is None:
                break
            self.game_list.remove(row)

        self.row_map.clear()
        query = self.search_entry.get_text().strip().lower() if hasattr(self, "search_entry") else ""
        if query:
            self.filtered_games = [game for game in self.games if query in game.name.lower()]
        else:
            self.filtered_games = self.games[:]

        self._update_summary()

        for game in self.filtered_games:
            row = GameRow(game)
            self.row_map[game.appid] = row
            self.game_list.append(row)

    def _update_summary(self) -> None:
        enabled_count = sum(1 for game in self.games if game.enabled)
        self.summary_label.set_label(f"{len(self.filtered_games)} shown • {enabled_count} active profiles")

    def _select_game(self, game: Game) -> None:
        self.current_game = game
        self.block_updates = True
        self.split_view.set_show_content(True)
        self.title_label.set_label(game.name)
        self.path_label.set_label(str(game.install_path))
        self.enabled_row.set_active(game.enabled)
        self.profile_name_row.set_text(game.profile_name)
        self.multiplier_row.set_value(game.multiplier)
        self.flow_scale.set_value(game.flow_scale)
        self.performance_row.set_active(game.performance_mode)
        self.pacing_row.set_selected(0)
        self.gpu_row.set_text(game.gpu)
        self.execs_label.set_label("\n".join(game.executables) if game.executables else "No obvious executable detected.")
        if game.matched_profile_name:
            self.meta_label.set_label(f"Mapped to existing profile: {game.matched_profile_name}")
        elif game.enabled:
            self.meta_label.set_label("Managed profile enabled")
        else:
            self.meta_label.set_label("No lsfg-vk profile enabled for this game")
        self.block_updates = False

    def _save_current_fields(self) -> None:
        if self.block_updates or not self.current_game:
            return
        game = self.current_game
        game.enabled = self.enabled_row.get_active()
        game.profile_name = self.profile_name_row.get_text().strip() or f"{game.name} 2x FG"
        game.multiplier = int(self.multiplier_row.get_value())
        game.flow_scale = round(self.flow_scale.get_value(), 2)
        game.performance_mode = self.performance_row.get_active()
        game.pacing = self.pacing_model.get_string(self.pacing_row.get_selected())
        game.gpu = self.gpu_row.get_text().strip() or GPU_NAME
        row = self.row_map.get(game.appid)
        if row:
            row.refresh()

    def _persist(self) -> None:
        self._save_current_fields()
        self.config.save_games(self.games)
        self._update_summary()
        if self.current_game:
            row = self.row_map.get(self.current_game.appid)
            if row:
                row.refresh()
            self._select_game(self.current_game)

    def _show_toast(self, title: str) -> None:
        self.toast_overlay.add_toast(Adw.Toast.new(title))

    def _schedule_autosave(self) -> None:
        if self.block_updates:
            return
        if self.autosave_source_id is not None:
            GLib.source_remove(self.autosave_source_id)
        self.autosave_source_id = GLib.timeout_add(250, self._run_autosave)

    def _run_autosave(self) -> bool:
        self.autosave_source_id = None
        self._persist()
        return GLib.SOURCE_REMOVE

    def _flush_autosave(self) -> None:
        if self.autosave_source_id is None:
            return
        GLib.source_remove(self.autosave_source_id)
        self.autosave_source_id = None
        self._persist()

    def _on_reload_clicked(self, _button: Gtk.Button) -> None:
        self._flush_autosave()
        self.config.load()
        self.games = load_games(self.config)
        self._reload_list()
        if self.filtered_games:
            self._select_game(self.filtered_games[0])
        self._show_toast("Steam library rescanned")

    def _on_search_changed(self, _entry: Gtk.SearchEntry) -> None:
        current_appid = self.current_game.appid if self.current_game else None
        self._reload_list()
        if current_appid and current_appid in self.row_map:
            self.game_list.select_row(self.row_map[current_appid])
        elif self.filtered_games:
            self.game_list.select_row(self.row_map[self.filtered_games[0].appid])

    def _on_row_selected(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if row is None or not isinstance(row, GameRow):
            return
        self._save_current_fields()
        self._select_game(row.game)

    def _on_enabled_toggled(self, _row: Adw.SwitchRow, _pspec: GObject.ParamSpec) -> None:
        self._save_current_fields()
        self._schedule_autosave()

    def _on_profile_field_changed(self, *_args: Any) -> None:
        self._save_current_fields()
        self._schedule_autosave()


class LsfgManagerApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)

    def do_activate(self) -> None:
        window = self.props.active_window
        if not window:
            window = LsfgManagerWindow(self)
        window.present()

def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--smoke-test":
        config = ConfigStore(LSFG_CONFIG)
        games = load_games(config)
        print(f"games={len(games)} enabled={sum(1 for game in games if game.enabled)}")
        if games:
            print(f"first={games[0].name}")
        return

    app = LsfgManagerApplication()
    app.run(None)


if __name__ == "__main__":
    main()

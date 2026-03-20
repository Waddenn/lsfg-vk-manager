from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk

from .config_store import ConfigStore
from .constants import APP_ID
from .gpu import GPU_FALLBACK_NAME
from .library import load_games
from .models import Game
from .settings import SettingsStore, SourceSettings, inspect_source_warnings, validate_sources
from .utils import format_error_message


AUTOSAVE_DELAY_MS = 800


@dataclass(frozen=True)
class GameFormState:
    enabled: bool
    profile_name: str
    multiplier: int
    flow_scale: float
    performance_mode: bool
    pacing: str
    gpu: str
    executables: tuple[str, ...]


@dataclass(frozen=True)
class SaveIndicatorState:
    text: str
    css_class: str | None = None


def make_game_form_state(game: Game, default_gpu: str) -> GameFormState:
    return GameFormState(
        enabled=game.enabled,
        profile_name=game.profile_name.strip() or f"{game.name} 2x FG",
        multiplier=game.multiplier,
        flow_scale=round(game.flow_scale, 2),
        performance_mode=game.performance_mode,
        pacing=game.pacing.strip() or "none",
        gpu=game.gpu.strip() or default_gpu or GPU_FALLBACK_NAME,
        executables=tuple(game.executables),
    )


def describe_profile_source(game: Game) -> str:
    ryujinx_hint = ""
    if game.appid.startswith("custom:ryujinx:") and game.executables:
        ryujinx_hint = f"\nRyujinx launch hint: LSFG_PROCESS={game.executables[0]}"
    if game.profile_source == "managed":
        return f"Managed profile enabled{ryujinx_hint}"
    if game.profile_source == "existing" and game.matched_profile_name:
        return f"Using existing profile: {game.matched_profile_name}{ryujinx_hint}"
    if game.enabled:
        return f"Managed profile enabled{ryujinx_hint}"
    return f"No lsfg-vk profile enabled for this game{ryujinx_hint}"


def compute_save_indicator(
    current_game: Game | None,
    last_persisted_state: GameFormState | None,
    default_gpu: str,
    autosave_pending: bool,
) -> SaveIndicatorState:
    if current_game is None:
        return SaveIndicatorState("No pending changes")
    current_state = make_game_form_state(current_game, default_gpu)
    if last_persisted_state == current_state:
        return SaveIndicatorState("Saved", "success")
    if autosave_pending:
        return SaveIndicatorState("Saving…", "accent")
    return SaveIndicatorState("Unsaved changes", "warning")


def apply_enabled_state_to_games(games: list[Game], enabled: bool, default_gpu: str) -> int:
    changed = 0
    for game in games:
        if game.enabled == enabled:
            continue
        game.enabled = enabled
        if enabled:
            game.profile_name = game.profile_name.strip() or f"{game.name} 2x FG"
            game.pacing = game.pacing.strip() or "none"
            game.gpu = game.gpu.strip() or default_gpu or GPU_FALLBACK_NAME
            if not game.executables:
                game.executables = game.detected_executables[:]
            if game.profile_source != "existing":
                game.profile_source = "managed"
        else:
            game.profile_source = None
        changed += 1
    return changed


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
        return f"{state} • {execs} executable target{'s' if execs != 1 else ''}"


class LsfgManagerWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, title="LSFG Game Manager")
        self.set_default_size(1180, 760)

        self.settings_store = SettingsStore()
        self.sources = self.settings_store.sources
        self.config = ConfigStore(
            self.sources.lsfg_config_path,
            default_dll=self.sources.lossless_dll_path,
            managed_metadata=self.settings_store.managed_profiles,
        )
        self.games = load_games(self.config, self.sources)
        self.filtered_games = self.games[:]
        self.current_game: Game | None = None
        self.row_map: dict[str, GameRow] = {}
        self.block_updates = False
        self.autosave_source_id: int | None = None
        self.last_persisted_state: GameFormState | None = None

        self._build_ui()
        self._reload_list()
        if self.filtered_games:
            self._select_game(self.filtered_games[0])
        else:
            self._show_empty_state()

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
        reload_button.set_tooltip_text("Rescan detected games")
        reload_button.connect("clicked", self._on_reload_clicked)
        header.pack_start(reload_button)

        enable_all_button = Gtk.Button(label="Enable All")
        enable_all_button.add_css_class("flat")
        enable_all_button.set_tooltip_text("Enable lsfg-vk for all detected games")
        enable_all_button.connect("clicked", self._on_enable_all_clicked)
        header.pack_start(enable_all_button)

        disable_all_button = Gtk.Button(label="Disable All")
        disable_all_button.add_css_class("flat")
        disable_all_button.set_tooltip_text("Disable manager-controlled profiles for all detected games")
        disable_all_button.connect("clicked", self._on_disable_all_clicked)
        header.pack_start(disable_all_button)

        settings_button = Gtk.Button(icon_name="emblem-system-symbolic")
        settings_button.add_css_class("flat")
        settings_button.set_tooltip_text("Edit source settings")
        settings_button.connect("clicked", self._on_settings_clicked)
        header.pack_end(settings_button)

        self.save_state_label = Gtk.Label(xalign=1)
        self.save_state_label.add_css_class("dim-label")
        self.save_state_label.add_css_class("save-state-chip")
        header.pack_end(self.save_state_label)

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
            .save-state-chip {
                background: alpha(@accent_bg_color, 0.08);
                border-radius: 999px;
                padding: 4px 10px;
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
        search.set_placeholder_text("Search detected games")
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

        self.pacing_row = Adw.EntryRow(title="Pacing")
        self.pacing_row.set_text("none")
        self.pacing_row.connect("notify::text", self._on_profile_field_changed)
        advanced_group.add(self.pacing_row)

        self.gpu_row = Adw.EntryRow(title="GPU")
        self.gpu_row.connect("notify::text", self._on_profile_field_changed)
        advanced_group.add(self.gpu_row)

        exec_header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        exec_title = Gtk.Label(xalign=0, label="Active executables")
        exec_title.add_css_class("title-4")
        exec_subtitle = Gtk.Label(
            xalign=0,
            label="One entry per line. Edit this list if auto-detection picked the wrong executable.",
        )
        exec_subtitle.add_css_class("dim-label")
        exec_subtitle.set_wrap(True)
        exec_header.append(exec_title)
        exec_header.append(exec_subtitle)
        outer.append(exec_header)

        exec_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        exec_actions.set_halign(Gtk.Align.END)
        reset_execs_button = Gtk.Button(label="Reset to detected")
        reset_execs_button.add_css_class("flat")
        reset_execs_button.connect("clicked", self._on_reset_executables_clicked)
        exec_actions.append(reset_execs_button)
        outer.append(exec_actions)

        exec_frame = Gtk.Frame()
        self.execs_buffer = Gtk.TextBuffer()
        self.execs_view = Gtk.TextView(buffer=self.execs_buffer)
        self.execs_view.add_css_class("mono-block")
        self.execs_view.set_wrap_mode(Gtk.WrapMode.NONE)
        self.execs_view.set_monospace(True)
        self.execs_view.set_top_margin(12)
        self.execs_view.set_bottom_margin(12)
        self.execs_view.set_left_margin(12)
        self.execs_view.set_right_margin(12)
        self.execs_buffer.connect("changed", self._on_profile_field_changed)
        exec_scroll = Gtk.ScrolledWindow()
        exec_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        exec_scroll.set_min_content_height(140)
        exec_scroll.set_child(self.execs_view)
        exec_frame.set_child(exec_scroll)
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
        source_issues = validate_sources(self.sources)
        source_warnings = inspect_source_warnings(self.sources)
        summary = f"{len(self.filtered_games)} shown • {enabled_count} active profiles"
        if source_issues:
            summary = f"{summary} • source errors detected"
        elif source_warnings:
            summary = f"{summary} • source warnings detected"
        self.summary_label.set_label(summary)
        self._update_status(source_issues, source_warnings)

    def _update_status(self, source_issues: list[str], source_warnings: list[str]) -> None:
        if source_issues:
            self.status_label.set_label("\n".join(source_issues[:3]))
            self.status_label.add_css_class("error")
            return
        if source_warnings:
            self.status_label.set_label("\n".join(source_warnings[:3]))
            self.status_label.remove_css_class("error")
            return

        status = f"Using Steam source: {self.sources.steam_apps_path}"
        if self.games:
            status = f"{status} • library ready"
        else:
            status = f"{status} • no games detected"
        self.status_label.set_label(status)
        self.status_label.remove_css_class("error")

    def _show_empty_state(self) -> None:
        self.current_game = None
        self.block_updates = True
        self.split_view.set_show_content(True)
        source_issues = validate_sources(self.sources)
        source_warnings = inspect_source_warnings(self.sources)
        search_query = self.search_entry.get_text().strip() if hasattr(self, "search_entry") else ""
        if search_query:
            self.title_label.set_label("No matching games")
            self.path_label.set_label(search_query)
            self.meta_label.set_label("Try a broader search or clear the filter.")
        else:
            self.title_label.set_label("No games detected")
            self.path_label.set_label(str(self.sources.steam_apps_path))
            if source_issues:
                self.meta_label.set_label("Library sources need attention. Open settings to fix the paths.")
            elif source_warnings:
                self.meta_label.set_label("Some configured paths are missing, but the sources can still be saved.")
            else:
                self.meta_label.set_label("No supported game was found in the configured sources.")
        self.enabled_row.set_active(False)
        self.profile_name_row.set_text("")
        self.multiplier_row.set_value(2)
        self.flow_scale.set_value(1.0)
        self.performance_row.set_active(False)
        self.pacing_row.set_text("none")
        self.gpu_row.set_text(self.sources.default_gpu or GPU_FALLBACK_NAME)
        self.execs_buffer.set_text("")
        self.block_updates = False
        self.last_persisted_state = None
        self._update_save_indicator()

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
        self.pacing_row.set_text(game.pacing)
        self.gpu_row.set_text(game.gpu)
        self.execs_buffer.set_text("\n".join(game.executables))
        self.meta_label.set_label(describe_profile_source(game))
        self.block_updates = False
        self.last_persisted_state = make_game_form_state(game, self.sources.default_gpu)
        self._update_save_indicator()

    def _save_current_fields(self) -> None:
        if self.block_updates or not self.current_game:
            return
        game = self.current_game
        game.enabled = self.enabled_row.get_active()
        game.profile_name = self.profile_name_row.get_text().strip() or f"{game.name} 2x FG"
        game.multiplier = int(self.multiplier_row.get_value())
        game.flow_scale = round(self.flow_scale.get_value(), 2)
        game.performance_mode = self.performance_row.get_active()
        game.pacing = self.pacing_row.get_text().strip() or "none"
        game.gpu = self.gpu_row.get_text().strip() or self.sources.default_gpu or GPU_FALLBACK_NAME
        start = self.execs_buffer.get_start_iter()
        end = self.execs_buffer.get_end_iter()
        game.executables = self._parse_executables_text(self.execs_buffer.get_text(start, end, False))
        if game.enabled and game.profile_source != "existing":
            game.profile_source = "managed"
        if not game.enabled:
            game.profile_source = None
        row = self.row_map.get(game.appid)
        if row:
            row.refresh()

    def _persist(self) -> bool:
        self._save_current_fields()
        try:
            self.config.save_games(self.games)
            self.settings_store.write()
        except Exception as exc:
            self._report_runtime_error("Save failed", exc)
            return False
        self._update_summary()
        if self.current_game:
            row = self.row_map.get(self.current_game.appid)
            if row:
                row.refresh()
            self._select_game(self.current_game)
            self.last_persisted_state = make_game_form_state(self.current_game, self.sources.default_gpu)
        return True

    def _show_toast(self, title: str) -> None:
        self.toast_overlay.add_toast(Adw.Toast.new(title))

    def _report_runtime_error(self, action: str, exc: Exception) -> None:
        message = f"{action}: {format_error_message(exc)}"
        self.status_label.set_label(message)
        self.status_label.add_css_class("error")
        self._show_toast(message)

    def _update_save_indicator(self) -> None:
        indicator = compute_save_indicator(
            self.current_game,
            self.last_persisted_state,
            self.sources.default_gpu,
            self.autosave_source_id is not None,
        )
        self.save_state_label.set_label(indicator.text)
        for css_class in ("success", "warning", "accent"):
            self.save_state_label.remove_css_class(css_class)
        if indicator.css_class:
            self.save_state_label.add_css_class(indicator.css_class)

    def _parse_executables_text(self, text: str) -> list[str]:
        seen: set[str] = set()
        entries: list[str] = []
        for line in text.splitlines():
            entry = line.strip()
            if not entry:
                continue
            key = entry.lower()
            if key in seen:
                continue
            seen.add(key)
            entries.append(entry)
        return entries

    def _schedule_autosave(self) -> None:
        if self.block_updates:
            return
        if self.current_game and self.last_persisted_state == make_game_form_state(self.current_game, self.sources.default_gpu):
            self._update_save_indicator()
            return
        if self.autosave_source_id is not None:
            GLib.source_remove(self.autosave_source_id)
        self.autosave_source_id = GLib.timeout_add(AUTOSAVE_DELAY_MS, self._run_autosave)
        self._update_save_indicator()

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
        try:
            self.config.load()
            self.games = load_games(self.config, self.sources)
            self._reload_list()
            if self.filtered_games:
                self._select_game(self.filtered_games[0])
            else:
                self._show_empty_state()
        except Exception as exc:
            self._report_runtime_error("Reload failed", exc)
            return
        self._show_toast("Game library rescanned")

    def _apply_enabled_state_to_library(self, enabled: bool) -> None:
        self._flush_autosave()
        changed = apply_enabled_state_to_games(self.games, enabled, self.sources.default_gpu)
        if not changed:
            self._show_toast("No library changes needed")
            return
        if not self._persist():
            return
        self._reload_list()
        if self.current_game and self.current_game.appid in self.row_map:
            self.game_list.select_row(self.row_map[self.current_game.appid])
        elif self.filtered_games:
            self.game_list.select_row(self.row_map[self.filtered_games[0].appid])
        else:
            self._show_empty_state()
        action = "enabled" if enabled else "disabled"
        self._show_toast(f"{changed} game profiles {action}")

    def _rebuild_data(self) -> None:
        self.config = ConfigStore(
            self.sources.lsfg_config_path,
            default_dll=self.sources.lossless_dll_path,
            managed_metadata=self.settings_store.managed_profiles,
        )
        self.games = load_games(self.config, self.sources)
        self.filtered_games = self.games[:]
        self.current_game = None
        self._reload_list()
        if self.filtered_games:
            self._select_game(self.filtered_games[0])
        else:
            self._show_empty_state()

    def _open_settings_window(self) -> None:
        window = Adw.PreferencesWindow(transient_for=self, modal=True, title="Sources")
        window.set_default_size(760, 420)

        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            title="Paths",
            description="Override auto-detected locations for Steam, Hytale, Ryujinx and lsfg-vk.",
        )
        page.add(group)

        self.settings_window = window
        self.settings_steam_apps_row = Adw.EntryRow(title="Steam steamapps")
        self.settings_steam_apps_row.set_text(self.sources.steam_apps)
        self.settings_steam_apps_row.add_suffix(self._make_browse_button("folder", self.settings_steam_apps_row))
        group.add(self.settings_steam_apps_row)

        self.settings_steam_common_row = Adw.EntryRow(title="Steam common")
        self.settings_steam_common_row.set_text(self.sources.steam_common)
        self.settings_steam_common_row.add_suffix(self._make_browse_button("folder", self.settings_steam_common_row))
        group.add(self.settings_steam_common_row)

        self.settings_hytale_release_row = Adw.EntryRow(title="Hytale release")
        self.settings_hytale_release_row.set_text(self.sources.hytale_release)
        self.settings_hytale_release_row.add_suffix(self._make_browse_button("folder", self.settings_hytale_release_row))
        group.add(self.settings_hytale_release_row)

        self.settings_ryujinx_config_row = Adw.EntryRow(title="Ryujinx Config.json")
        self.settings_ryujinx_config_row.set_text(self.sources.ryujinx_config)
        self.settings_ryujinx_config_row.add_suffix(self._make_browse_button("file", self.settings_ryujinx_config_row))
        group.add(self.settings_ryujinx_config_row)

        self.settings_lsfg_config_row = Adw.EntryRow(title="lsfg-vk conf.toml")
        self.settings_lsfg_config_row.set_text(self.sources.lsfg_config)
        self.settings_lsfg_config_row.add_suffix(self._make_browse_button("file", self.settings_lsfg_config_row))
        group.add(self.settings_lsfg_config_row)

        self.settings_default_gpu_row = Adw.EntryRow(title="Default GPU")
        self.settings_default_gpu_row.set_text(self.sources.default_gpu)
        group.add(self.settings_default_gpu_row)

        help_group = Adw.PreferencesGroup(title="Derived value")
        dll_row = Adw.ActionRow(title="Default Lossless DLL path")
        dll_row.set_subtitle(
            str(
                SourceSettings(
                    steam_apps=self.settings_steam_apps_row.get_text(),
                    steam_common=self.settings_steam_common_row.get_text(),
                    hytale_release=self.settings_hytale_release_row.get_text(),
                    ryujinx_config=self.settings_ryujinx_config_row.get_text(),
                    lsfg_config=self.settings_lsfg_config_row.get_text(),
                    default_gpu=self.settings_default_gpu_row.get_text(),
                ).lossless_dll_path
            )
        )
        help_group.add(dll_row)
        self.settings_dll_row = dll_row

        validation_group = Adw.PreferencesGroup(title="Validation")
        validation_row = Adw.ActionRow(title="Source check")
        validation_row.set_subtitle("")
        validation_group.add(validation_row)
        self.settings_validation_row = validation_row

        actions_group = Adw.PreferencesGroup(title="Actions")
        save_row = Adw.ActionRow(title="Save source settings")
        save_row.set_activatable(False)
        save_button = Gtk.Button(label="Save")
        save_button.add_css_class("suggested-action")
        save_button.set_halign(Gtk.Align.END)
        save_button.set_valign(Gtk.Align.CENTER)
        save_button.connect("clicked", self._on_settings_save_clicked)
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        button_box.set_halign(Gtk.Align.END)
        button_box.append(save_button)
        save_row.add_suffix(button_box)
        actions_group.add(save_row)

        for row in (
            self.settings_steam_apps_row,
            self.settings_steam_common_row,
            self.settings_hytale_release_row,
            self.settings_ryujinx_config_row,
            self.settings_lsfg_config_row,
            self.settings_default_gpu_row,
        ):
            row.connect("notify::text", self._on_settings_field_changed)

        page.add(help_group)
        page.add(validation_group)
        page.add(actions_group)
        window.add(page)
        self._refresh_settings_preview()
        window.present()

    def _refresh_settings_preview(self) -> None:
        if not hasattr(self, "settings_dll_row"):
            return
        preview = SourceSettings(
            steam_apps=self.settings_steam_apps_row.get_text().strip() or self.sources.steam_apps,
            steam_common=self.settings_steam_common_row.get_text().strip() or self.sources.steam_common,
            hytale_release=self.settings_hytale_release_row.get_text().strip() or self.sources.hytale_release,
            ryujinx_config=self.settings_ryujinx_config_row.get_text().strip() or self.sources.ryujinx_config,
            lsfg_config=self.settings_lsfg_config_row.get_text().strip() or self.sources.lsfg_config,
            default_gpu=self.settings_default_gpu_row.get_text().strip() or self.sources.default_gpu,
        )
        self.settings_dll_row.set_subtitle(str(preview.lossless_dll_path))
        issues = validate_sources(preview)
        warnings = inspect_source_warnings(preview)
        if hasattr(self, "settings_validation_row"):
            if issues:
                self.settings_validation_row.set_title("Source check: issues found")
                self.settings_validation_row.set_subtitle("\n".join(issues))
            elif warnings:
                self.settings_validation_row.set_title("Source check: warnings only")
                self.settings_validation_row.set_subtitle("\n".join(warnings))
            else:
                self.settings_validation_row.set_title("Source check: ready")
                self.settings_validation_row.set_subtitle("All configured paths look usable.")

    def _apply_settings_from_form(self) -> bool:
        candidate = SourceSettings(
            steam_apps=self.settings_steam_apps_row.get_text().strip() or self.sources.steam_apps,
            steam_common=self.settings_steam_common_row.get_text().strip() or self.sources.steam_common,
            hytale_release=self.settings_hytale_release_row.get_text().strip() or self.sources.hytale_release,
            ryujinx_config=self.settings_ryujinx_config_row.get_text().strip() or self.sources.ryujinx_config,
            lsfg_config=self.settings_lsfg_config_row.get_text().strip() or self.sources.lsfg_config,
            default_gpu=self.settings_default_gpu_row.get_text().strip() or self.sources.default_gpu,
        )
        issues = validate_sources(candidate)
        if issues:
            self._show_toast(issues[0])
            self._refresh_settings_preview()
            return False
        previous_sources = self.sources
        try:
            self.sources = candidate
            self.settings_store.sources = self.sources
            self.settings_store.write()
            self._rebuild_data()
        except Exception as exc:
            self.sources = previous_sources
            self.settings_store.sources = previous_sources
            self._report_runtime_error("Saving sources failed", exc)
            self._refresh_settings_preview()
            return False
        return True

    def _make_browse_button(self, chooser_kind: str, row: Adw.EntryRow) -> Gtk.Button:
        button = Gtk.Button(icon_name="document-open-symbolic")
        button.add_css_class("flat")
        button.set_valign(Gtk.Align.CENTER)
        button.set_tooltip_text("Browse")
        button.connect("clicked", self._on_browse_clicked, chooser_kind, row)
        return button

    def _open_file_dialog(self, chooser_kind: str, row: Adw.EntryRow) -> None:
        dialog = Gtk.FileDialog(title="Select path")
        current = row.get_text().strip()
        if current:
            initial_path = Gio.File.new_for_path(current)
            try:
                dialog.set_initial_file(initial_path)
            except Exception:
                pass

        if chooser_kind == "file":
            dialog.open(self.settings_window, None, self._on_file_dialog_complete, row)
        else:
            dialog.select_folder(self.settings_window, None, self._on_folder_dialog_complete, row)

    def _on_browse_clicked(self, _button: Gtk.Button, chooser_kind: str, row: Adw.EntryRow) -> None:
        self._open_file_dialog(chooser_kind, row)

    def _on_file_dialog_complete(
        self,
        dialog: Gtk.FileDialog,
        result: Gio.AsyncResult,
        row: Adw.EntryRow,
    ) -> None:
        try:
            file = dialog.open_finish(result)
        except GLib.Error:
            return
        if file is not None and file.get_path():
            row.set_text(file.get_path())

    def _on_folder_dialog_complete(
        self,
        dialog: Gtk.FileDialog,
        result: Gio.AsyncResult,
        row: Adw.EntryRow,
    ) -> None:
        try:
            file = dialog.select_folder_finish(result)
        except GLib.Error:
            return
        if file is not None and file.get_path():
            row.set_text(file.get_path())

    def _on_settings_clicked(self, _button: Gtk.Button) -> None:
        self._flush_autosave()
        self._open_settings_window()

    def _on_settings_field_changed(self, *_args: Any) -> None:
        self._refresh_settings_preview()

    def _on_settings_save_clicked(self, _button: Gtk.Button) -> None:
        if self._apply_settings_from_form():
            if hasattr(self, "settings_window"):
                self.settings_window.close()
            self._show_toast("Sources saved and library rescanned")

    def _on_reset_executables_clicked(self, _button: Gtk.Button) -> None:
        if not self.current_game:
            return
        self.block_updates = True
        self.current_game.executables = self.current_game.detected_executables[:] or []
        self.execs_buffer.set_text("\n".join(self.current_game.executables))
        self.block_updates = False
        self._save_current_fields()
        self._schedule_autosave()

    def _on_enable_all_clicked(self, _button: Gtk.Button) -> None:
        self._apply_enabled_state_to_library(True)

    def _on_disable_all_clicked(self, _button: Gtk.Button) -> None:
        self._apply_enabled_state_to_library(False)

    def _on_search_changed(self, _entry: Gtk.SearchEntry) -> None:
        current_appid = self.current_game.appid if self.current_game else None
        self._reload_list()
        if current_appid and current_appid in self.row_map:
            self.game_list.select_row(self.row_map[current_appid])
        elif self.filtered_games:
            self.game_list.select_row(self.row_map[self.filtered_games[0].appid])
        else:
            self._show_empty_state()

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


def run_app() -> None:
    app = LsfgManagerApplication()
    app.run(None)

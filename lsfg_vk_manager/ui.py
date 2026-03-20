from __future__ import annotations

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
from .settings import SettingsStore, SourceSettings


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

        self.settings_store = SettingsStore()
        self.sources = self.settings_store.sources
        self.config = ConfigStore(self.sources.lsfg_config_path, default_dll=self.sources.lossless_dll_path)
        self.games = load_games(self.config, self.sources)
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
        reload_button.set_tooltip_text("Rescan detected games")
        reload_button.connect("clicked", self._on_reload_clicked)
        header.pack_start(reload_button)

        settings_button = Gtk.Button(icon_name="emblem-system-symbolic")
        settings_button.add_css_class("flat")
        settings_button.set_tooltip_text("Edit source settings")
        settings_button.connect("clicked", self._on_settings_clicked)
        header.pack_end(settings_button)

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
            label="Auto-detected from the install folder. These are written to active_in.",
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
        game.gpu = self.gpu_row.get_text().strip() or self.sources.default_gpu or GPU_FALLBACK_NAME
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
        self.games = load_games(self.config, self.sources)
        self._reload_list()
        if self.filtered_games:
            self._select_game(self.filtered_games[0])
        self._show_toast("Game library rescanned")

    def _rebuild_data(self) -> None:
        self.config = ConfigStore(self.sources.lsfg_config_path, default_dll=self.sources.lossless_dll_path)
        self.games = load_games(self.config, self.sources)
        self.filtered_games = self.games[:]
        self.current_game = None
        self._reload_list()
        if self.filtered_games:
            self._select_game(self.filtered_games[0])

    def _open_settings_window(self) -> None:
        window = Adw.PreferencesWindow(transient_for=self, modal=True, title="Sources")
        window.set_default_size(760, 420)

        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            title="Paths",
            description="Override auto-detected locations for Steam, Hytale and lsfg-vk.",
        )
        page.add(group)

        self.settings_window = window
        self.settings_steam_apps_row = Adw.EntryRow(title="Steam steamapps")
        self.settings_steam_apps_row.set_text(self.sources.steam_apps)
        group.add(self.settings_steam_apps_row)

        self.settings_steam_common_row = Adw.EntryRow(title="Steam common")
        self.settings_steam_common_row.set_text(self.sources.steam_common)
        group.add(self.settings_steam_common_row)

        self.settings_hytale_release_row = Adw.EntryRow(title="Hytale release")
        self.settings_hytale_release_row.set_text(self.sources.hytale_release)
        group.add(self.settings_hytale_release_row)

        self.settings_lsfg_config_row = Adw.EntryRow(title="lsfg-vk conf.toml")
        self.settings_lsfg_config_row.set_text(self.sources.lsfg_config)
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
                    lsfg_config=self.settings_lsfg_config_row.get_text(),
                    default_gpu=self.settings_default_gpu_row.get_text(),
                ).lossless_dll_path
            )
        )
        help_group.add(dll_row)
        self.settings_dll_row = dll_row

        actions_group = Adw.PreferencesGroup(title="Actions")
        save_row = Adw.ActionRow(title="Save source settings")
        save_button = Gtk.Button(label="Save")
        save_button.add_css_class("suggested-action")
        save_button.connect("clicked", self._on_settings_save_clicked)
        save_row.add_suffix(save_button)
        actions_group.add(save_row)

        for row in (
            self.settings_steam_apps_row,
            self.settings_steam_common_row,
            self.settings_hytale_release_row,
            self.settings_lsfg_config_row,
            self.settings_default_gpu_row,
        ):
            row.connect("notify::text", self._on_settings_field_changed)

        page.add(help_group)
        page.add(actions_group)
        window.add(page)
        window.present()

    def _refresh_settings_preview(self) -> None:
        if not hasattr(self, "settings_dll_row"):
            return
        preview = SourceSettings(
            steam_apps=self.settings_steam_apps_row.get_text().strip() or self.sources.steam_apps,
            steam_common=self.settings_steam_common_row.get_text().strip() or self.sources.steam_common,
            hytale_release=self.settings_hytale_release_row.get_text().strip() or self.sources.hytale_release,
            lsfg_config=self.settings_lsfg_config_row.get_text().strip() or self.sources.lsfg_config,
            default_gpu=self.settings_default_gpu_row.get_text().strip() or self.sources.default_gpu,
        )
        self.settings_dll_row.set_subtitle(str(preview.lossless_dll_path))

    def _apply_settings_from_form(self) -> None:
        self.sources = SourceSettings(
            steam_apps=self.settings_steam_apps_row.get_text().strip() or self.sources.steam_apps,
            steam_common=self.settings_steam_common_row.get_text().strip() or self.sources.steam_common,
            hytale_release=self.settings_hytale_release_row.get_text().strip() or self.sources.hytale_release,
            lsfg_config=self.settings_lsfg_config_row.get_text().strip() or self.sources.lsfg_config,
            default_gpu=self.settings_default_gpu_row.get_text().strip() or self.sources.default_gpu,
        )
        self.settings_store.sources = self.sources
        self.settings_store.write()
        self._rebuild_data()

    def _on_settings_clicked(self, _button: Gtk.Button) -> None:
        self._flush_autosave()
        self._open_settings_window()

    def _on_settings_field_changed(self, *_args: Any) -> None:
        self._refresh_settings_preview()

    def _on_settings_save_clicked(self, _button: Gtk.Button) -> None:
        self._apply_settings_from_form()
        if hasattr(self, "settings_window"):
            self.settings_window.close()
        self._show_toast("Sources saved and library rescanned")

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


def run_app() -> None:
    app = LsfgManagerApplication()
    app.run(None)

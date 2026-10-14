#!/usr/bin/env python3
"""Pipper — wireless phone displays for Hyprland, using GTK4 and wayvnc."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sys
import traceback

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

try:
    from .config_manager import (ConfigManager, HyprlandController, LAYERS, EDITORS,
        MonitorSettings, PipperError, WayVNCManager, dependency_status,
        install_dependencies, local_addresses)
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from src.config_manager import (ConfigManager, HyprlandController, LAYERS, EDITORS,
        MonitorSettings, PipperError, WayVNCManager, dependency_status,
        install_dependencies, local_addresses)

try:
    from .integrations import (Environment, detect_environment, install_vicinae_scripts,
                               noctalia_action, open_display_settings, refresh_vicinae_scripts)
    from .session import Session
    from .paths import command_argv, data_directory
except ImportError:
    from src.integrations import (Environment, detect_environment, install_vicinae_scripts,
                                  noctalia_action, open_display_settings, refresh_vicinae_scripts)
    from src.session import Session
    from src.paths import command_argv, data_directory

ASSETS = Path(__file__).resolve().parent


def label(text: str, css: str = "", wrap: bool = False) -> Gtk.Label:
    widget = Gtk.Label(label=text, xalign=0, wrap=wrap)
    if css:
        widget.add_css_class(css)
    return widget


def box(orientation=Gtk.Orientation.VERTICAL, spacing=12, css="") -> Gtk.Box:
    widget = Gtk.Box(orientation=orientation, spacing=spacing)
    if css:
        widget.add_css_class(css)
    return widget


def button(text: str, callback, css: str = "") -> Gtk.Button:
    widget = Gtk.Button(label=text)
    widget.connect("clicked", callback)
    if css:
        widget.add_css_class(css)
    return widget


class PipperWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application):
        super().__init__(application=app, title="Pipper", default_width=1000, default_height=820)
        self.set_icon_name("pipper")
        self.add_css_class("pipper")
        self.manager = ConfigManager()
        self.hypr = HyprlandController()
        self.vnc = WayVNCManager()
        self.session = Session(self.manager, self.hypr, self.vnc)
        self.environment = Environment()
        self.dependencies = {}
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pipper")
        self.presets = json.loads((ASSETS / "devices.json").read_text())
        self.loading = False
        self.busy = False
        self.closing = False
        self.active_output: str | None = None
        self.editor_process = None
        self.editor_settings = None
        self.ip = None
        self.switches = {}
        self.exclusion_states = dict.fromkeys(LAYERS, False)
        self.entries = {}
        self.actions = []
        self.editor_ids = list(EDITORS)
        self.connect("close-request", self._close_requested)
        self.connect("realize", self._set_wayland_app_id)
        self._build()
        self._set_fields(MonitorSettings.from_preset(self.presets[0]))
        self._async(self._initial_state, self._apply_initial, "Lendo configurações do sistema…")
        GLib.timeout_add_seconds(5, self._poll_vnc)
        GLib.timeout_add_seconds(30, self._poll_environment)

    def _set_wayland_app_id(self, *_):
        surface = self.get_surface()
        try:
            gi.require_version("GdkWayland", "4.0")
            from gi.repository import GdkWayland
        except (ValueError, ImportError):
            return
        if isinstance(surface, GdkWayland.WaylandToplevel):
            surface.set_application_id("pipper")

    def _build(self):
        header = Gtk.HeaderBar()
        header.set_show_title_buttons(False)
        title = box(Gtk.Orientation.HORIZONTAL, 10)
        brand_icon = Gtk.Image.new_from_icon_name("pipper")
        brand_icon.set_pixel_size(28)
        title.append(brand_icon)
        title.append(label("pipper", "header-title"))
        header.set_title_widget(title)
        self.set_titlebar(header)

        outer = box(spacing=0)
        self.set_child(outer)
        self.warning_box = box(Gtk.Orientation.HORIZONTAL, 12, "warning-banner")
        self.warning_label = label("", wrap=True)
        self.warning_label.set_hexpand(True)
        self.warning_box.append(self.warning_label)
        self.install_button = button("Instalar Dependências", self._install)
        self.warning_box.append(self.install_button)
        self.warning_box.set_visible(False)
        outer.append(self.warning_box)

        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        outer.append(scroll)
        content = box(spacing=22, css="content")
        scroll.set_child(content)

        intro = box(Gtk.Orientation.HORIZONTAL, 16)
        intro_text = box(spacing=6)
        intro_text.set_hexpand(True)
        intro_text.append(label("MAIS ESPAÇO PARA SUAS IDEIAS", "eyebrow"))
        intro_text.append(label("Seu próximo monitor cabe no bolso.", "title", True))
        intro_text.append(label("Escolha seu dispositivo, ajuste a posição e conecte pela rede local.", "muted", True))
        intro.append(intro_text)
        self.status_badge = label("● DESLIGADO", "status-badge")
        self.status_badge.set_valign(Gtk.Align.CENTER)
        intro.append(self.status_badge)
        content.append(intro)

        self.tabs = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE,
                              transition_duration=180, vhomogeneous=False, hhomogeneous=True)
        switcher = Gtk.StackSwitcher(stack=self.tabs, halign=Gtk.Align.START)
        switcher.add_css_class("tabs")
        content.append(switcher)
        content.append(self.tabs)

        columns = box(Gtk.Orientation.HORIZONTAL, 20)
        self.tabs.add_titled(columns, "device", "Dispositivo")
        position_page = box(Gtk.Orientation.HORIZONTAL, 20)
        self.tabs.add_titled(position_page, "position", "Posição")
        appearance_page = box(Gtk.Orientation.HORIZONTAL, 20)
        self.tabs.add_titled(appearance_page, "appearance", "Aparência")
        integrations_page = box(spacing=18)
        self.tabs.add_titled(integrations_page, "integrations", "Integrações")
        left = box(spacing=18)
        left.set_hexpand(True)
        columns.append(left)
        right = box(spacing=18)
        right.set_size_request(330, -1)
        columns.append(right)

        monitor_card = box(spacing=16, css="card")
        monitor_card.append(label("DISPOSITIVO", "eyebrow"))
        monitor_card.append(label("Configuração do dispositivo", "section-title"))
        self.form = box(spacing=14)
        monitor_card.append(self.form)
        device_label = label("Dispositivo", "field-label")
        self.form.append(device_label)
        self.dropdown = Gtk.DropDown.new_from_strings([preset["name"] for preset in self.presets])
        self.dropdown.set_enable_search(True)
        device_label.set_mnemonic_widget(self.dropdown)
        self.dropdown.set_selected(0)
        self.dropdown.connect("notify::selected", self._preset_selected)
        self.form.append(self.dropdown)
        self.form.append(label(f"{len(self.presets) - 1} perfis + personalizado · pesquise por marca ou modelo", "muted", True))
        performance_row = box(Gtk.Orientation.HORIZONTAL, 10)
        performance_row.append(label("Transmissão", "field-label"))
        self.performance = Gtk.DropDown.new_from_strings([
            "Perfil atual", "Economia · HD / 30 Hz", "Equilibrado · Full HD / 60 Hz", "Detalhe · QHD / 60 Hz"])
        self.performance.set_hexpand(True)
        self.performance.connect("notify::selected", self._performance_changed)
        performance_row.append(self.performance)
        self.form.append(performance_row)
        grid = Gtk.Grid(column_spacing=14, row_spacing=14)
        self.form.append(grid)
        fields = [("output", "Nome do Output", "S22"),
                  ("resolution", "Resolução", "1920x1080"),
                  ("refresh", "Atualização · Hz", "60"),
                  ("scale", "Escala", "2.0"),
                  ("position", "Posição · X × Y", "3552x1376"),
                  ("workspace", "Workspace do celular", "11")]
        for index, (key, title, placeholder) in enumerate(fields):
            field = box(spacing=7)
            caption = label(title, "field-label")
            field.append(caption)
            entry = Gtk.Entry(placeholder_text=placeholder, hexpand=True)
            entry.set_width_chars(12)
            entry.set_max_width_chars(20)
            caption.set_mnemonic_widget(entry)
            field.append(entry)
            grid.attach(field, index % 2, index // 2, 1, 1)
            self.entries[key] = entry
            if key == "workspace":
                entry.set_tooltip_text("Ao ligar, este workspace será movido para a tela do celular. Padrão: 11.")
            entry.connect("changed", self._refresh_summary)
        for key in ("scale", "resolution"):
            focus = Gtk.EventControllerFocus()
            focus.connect("leave", self._validate_on_leave)
            self.entries[key].add_controller(focus)
            self.entries[key].connect("activate", self._validate_on_leave)
        output_focus = Gtk.EventControllerFocus()
        output_focus.connect("leave", self._output_changed)
        self.entries["output"].add_controller(output_focus)
        self.form.append(button("Alternar retrato / paisagem", self._rotate))
        monitor_card.append(label("Perfis de transmissão editáveis; a resolução pode ser diferente da tela nativa do aparelho.", "muted", True))
        self.display_summary = label("", "summary-line", True)
        monitor_card.append(self.display_summary)
        left.append(monitor_card)

        position_card = box(spacing=12, css="card")
        position_card.set_hexpand(True)
        position_card.set_valign(Gtk.Align.START)
        position_card.append(label("POSICIONAMENTO", "eyebrow"))
        position_card.append(label("Organize sua área de trabalho", "section-title"))
        position_card.append(label("Use seu editor favorito. O Pipper prepara a tela e sincroniza os ajustes ao fechar.", "muted", True))
        self.editor_form = box(spacing=10)
        self.editor_form.append(label("Editor de monitores", "field-label"))
        self.editor_dropdown = Gtk.DropDown.new_from_strings(list(EDITORS.values()))
        self.editor_dropdown.connect("notify::selected", self._editor_changed)
        self.editor_form.append(self.editor_dropdown)
        self.custom_editor_box = box(spacing=7)
        self.custom_editor_box.append(label("Comando para abrir", "field-label"))
        self.custom_editor_entry = Gtk.Entry(placeholder_text="kitty -e hyprmon", hexpand=True)
        self.custom_editor_entry.connect("changed", self._editor_changed)
        self.custom_editor_box.append(self.custom_editor_entry)
        self.custom_editor_box.append(label("Pode incluir argumentos e caminhos entre aspas. Ex.: foot -e hyprmon", "muted", True))
        self.editor_form.append(self.custom_editor_box)
        self.editor_hint = label("", "command-hint", True)
        self.editor_form.append(self.editor_hint)
        position_card.append(self.editor_form)
        self._editor_changed()
        self.editor_button = button("Abrir Editor de Posição do Sistema", self._open_editor)
        self.sync_button = button("Sincronizar Posição Atual", self._sync)
        position_card.append(self.editor_button)
        position_card.append(self.sync_button)
        self.actions.extend([self.editor_button, self.sync_button])
        position_page.append(position_card)
        preview_card = box(spacing=15, css="preview-card")
        preview_card.set_size_request(330, -1)
        preview_card.set_valign(Gtk.Align.START)
        preview_card.append(label("PRÉVIA DA TELA", "eyebrow"))
        self.preview = Gtk.DrawingArea(content_width=270, content_height=170)
        self.preview.set_draw_func(self._draw_display)
        preview_card.append(self.preview)
        self.preview_mode = label("", "preview-mode")
        preview_card.append(self.preview_mode)
        self.preview_logical = label("", "muted", True)
        preview_card.append(self.preview_logical)
        preview_card.append(Gtk.Separator())
        preview_card.append(label("Como posicionar", "section-title"))
        preview_card.append(label("1. Abra o editor escolhido.\n2. Mova a tela do celular.\n3. Feche o editor ou sincronize.\n4. Salve para manter a posição.", "instructions", True))
        position_page.append(preview_card)

        connection = box(spacing=14, css="connection-card")
        connection.set_valign(Gtk.Align.START)
        connection.append(label("REDE LOCAL", "eyebrow"))
        connection.append(label("Conectar no Celular", "section-title"))
        connection.append(label("IP do Servidor", "field-label"))
        ip_row = box(Gtk.Orientation.HORIZONTAL, 8)
        self.ip_label = label("Detectando…", "ip-address")
        self.ip_label.set_selectable(True)
        self.ip_label.set_hexpand(True)
        ip_row.append(self.ip_label)
        self.copy_button = button("Copiar", self._copy_ip, "compact")
        self.copy_button.set_sensitive(False)
        ip_row.append(self.copy_button)
        connection.append(ip_row)
        connection.append(label("Porta: 5900", "muted"))
        self.address_dropdown = Gtk.DropDown.new_from_strings([])
        self.address_dropdown.set_visible(False)
        self.address_dropdown.connect("notify::selected", self._address_changed)
        connection.append(self.address_dropdown)
        self.qr = Gtk.DrawingArea(content_width=180, content_height=180, halign=Gtk.Align.CENTER)
        self.qr.set_draw_func(self._draw_qr)
        self.qr.set_visible(False)
        connection.append(self.qr)
        self.qr_matrix = None
        self.uri_label = label("", "connection-uri", True)
        self.uri_label.set_selectable(True)
        connection.append(self.uri_label)
        connection.append(label("1. Conecte o celular à mesma rede.\n2. Abra AVNC ou RealVNC.\n3. Adicione o IP e a porta acima.", "instructions", True))
        connection.append(label("Use o endereço da interface Wi-Fi/LAN acessível pelo celular.", "muted", True))
        connection.append(button("Atualizar IP", self._refresh_ip))
        self.copy_address_button = button("Copiar endereço VNC", self._copy_address)
        connection.append(self.copy_address_button)
        right.append(connection)

        noctalia = box(spacing=14, css="card")
        noctalia.set_hexpand(True)
        noctalia.set_valign(Gtk.Align.START)
        noctalia.append(label("NOCTALIA V5", "eyebrow"))
        noctalia.append(label("Ocultar na Tela do Celular", "section-title", True))
        self.noctalia_note = label("Verificando Noctalia na sessão atual…", "muted", True)
        noctalia.append(self.noctalia_note)
        for key, title in LAYERS.items():
            row = box(Gtk.Orientation.HORIZONTAL, 12, "layer-row")
            caption = box(spacing=5)
            caption.set_hexpand(True)
            caption.append(label(title, "layer-title", True))
            subtitles = {"bar.default": "Mais espaço para suas janelas", "dock": "Sem atalhos sobre o conteúdo",
                         "notifications": "Avisos apenas na tela principal", "osd": "Controles de volume e brilho discretos",
                         "mpris": "Música sem sobrepor sua segunda tela"}
            caption.append(label(subtitles[key], "muted", True))
            row.append(caption)
            switch = Gtk.Switch(valign=Gtk.Align.CENTER)
            switch.set_tooltip_text(f"Ocultar {title} no monitor configurado")
            switch.connect("notify::active", self._exclusion_changed, key)
            row.append(switch)
            noctalia.append(row)
            self.switches[key] = switch
        bulk_row = box(Gtk.Orientation.HORIZONTAL, 10)
        self.hide_all_button = button("Ocultar tudo", lambda *_: self._bulk_exclusions(True))
        self.show_all_button = button("Mostrar tudo", lambda *_: self._bulk_exclusions(False))
        bulk_row.append(self.hide_all_button)
        bulk_row.append(self.show_all_button)
        noctalia.append(bulk_row)
        appearance_page.append(noctalia)
        appearance_note = box(spacing=16, css="preview-card")
        appearance_note.set_size_request(330, -1)
        appearance_note.set_valign(Gtk.Align.START)
        appearance_note.append(label("DO SEU JEITO", "eyebrow"))
        icon = Gtk.Image.new_from_icon_name("preferences-desktop-display-symbolic")
        icon.set_pixel_size(64)
        icon.add_css_class("accent-icon")
        appearance_note.append(icon)
        appearance_note.append(label("Uma tela limpa para focar.", "section-title", True))
        appearance_note.append(label("Ative o que quer ocultar no celular. As outras telas continuam com sua configuração habitual.", "muted", True))
        appearance_note.append(label("✓ Salvo automaticamente\n✓ Backup antes de cada alteração", "instructions", True))
        child = appearance_note.get_first_child()
        while child:
            if isinstance(child, Gtk.Label):
                child.set_max_width_chars(32)
            child = child.get_next_sibling()
        appearance_page.append(appearance_note)

        environment_card = box(spacing=14, css="card")
        environment_card.append(label("SUA SESSÃO", "eyebrow"))
        self.environment_label = label("Detectando ambiente…", "section-title", True)
        environment_card.append(self.environment_label)
        self.compatibility_label = label("", "muted", True)
        environment_card.append(self.compatibility_label)
        environment_card.append(button("Verificar ambiente novamente", self._refresh_environment))
        self.native_display_button = button("Abrir configurações de tela do ambiente", self._native_display)
        environment_card.append(self.native_display_button)
        integrations_page.append(environment_card)

        integration_cards = box(Gtk.Orientation.HORIZONTAL, 18)
        integrations_page.append(integration_cards)
        hypr_card = box(spacing=12, css="card")
        hypr_card.set_hexpand(True)
        hypr_card.append(label("HYPRLAND", "eyebrow"))
        hypr_card.append(label("Sua tela a um atalho", "section-title"))
        self.hypr_status = label("", "muted", True)
        hypr_card.append(self.hypr_status)
        self.focus_button = button("Ir ao workspace do celular", self._focus_phone)
        hypr_card.append(self.focus_button)
        self.shortcut_button = button("Copiar comando para atalho", self._copy_shortcut)
        hypr_card.append(self.shortcut_button)
        hypr_card.append(label("Use o comando copiado em um atalho do Hyprland ou botão personalizado do Noctalia.", "muted", True))
        integration_cards.append(hypr_card)
        vicinae_card = box(spacing=12, css="card")
        vicinae_card.set_hexpand(True)
        vicinae_card.append(label("VICINAE", "eyebrow"))
        vicinae_card.append(label("Controle pelo launcher", "section-title"))
        self.vicinae_status = label("", "muted", True)
        vicinae_card.append(self.vicinae_status)
        vicinae_card.append(label("Busque Pipper para abrir o app, ligar/desligar, focar o workspace ou consultar a conexão.", "muted", True))
        self.vicinae_button = button("Adicionar comandos ao Vicinae", self._install_vicinae)
        vicinae_card.append(self.vicinae_button)
        integration_cards.append(vicinae_card)
        noctalia_card = box(spacing=12, css="card")
        noctalia_card.append(label("NOCTALIA V5", "eyebrow"))
        noctalia_card.append(label("Controles rápidos do shell", "section-title"))
        self.noctalia_status = label("", "muted", True)
        noctalia_card.append(self.noctalia_status)
        self.noctalia_buttons = []
        for title, action in (("Abrir configurações do Noctalia", "settings"),
                              ("Recarregar configurações", "reload"),
                              ("Alternar Não Perturbe no sistema", "dnd")):
            action_button = button(title, lambda _, a=action: self._noctalia_action(a))
            self.noctalia_buttons.append(action_button)
            noctalia_card.append(action_button)
        integrations_page.append(noctalia_card)
        diagnostics = box(spacing=12, css="preview-card")
        diagnostics.append(label("DIAGNÓSTICO", "eyebrow"))
        diagnostics.append(label("Ambiente, conexão e dependências em um resumo para copiar.", "muted", True))
        diagnostics.append(button("Copiar diagnóstico", self._copy_diagnostics))
        integrations_page.append(diagnostics)

        footer = box(spacing=12, css="footer")
        outer.append(footer)
        row = box(Gtk.Orientation.HORIZONTAL, 12)
        footer.append(row)
        self.spinner = Gtk.Spinner()
        row.append(self.spinner)
        self.message = label("Pronto para conectar.", "muted", True)
        self.message.set_hexpand(True)
        row.append(self.message)
        buttons = box(Gtk.Orientation.HORIZONTAL, 12)
        self.save_button = button("Salvar no hyprland.lua", self._save)
        self.power_button = button("Ligar Pipper", self._toggle, "primary")
        self.power_button.set_hexpand(True)
        buttons.append(self.save_button)
        buttons.append(self.power_button)
        self.actions.extend([self.save_button, self.power_button])
        footer.append(buttons)

    def _refresh_summary(self, *_):
        if not hasattr(self, "display_summary"):
            return
        try:
            width, height = map(int, self.entries["resolution"].get_text().split("x"))
            scale = Decimal(self.entries["scale"].get_text())
            if not scale.is_finite() or scale <= 0:
                raise ValueError()
            logical = f"{Decimal(width) / scale:.0f} × {Decimal(height) / scale:.0f}"
            refresh = self.entries["refresh"].get_text()
            self.display_summary.set_text(f"{width} × {height}  /  {refresh} Hz  /  escala {scale}")
            self.preview_mode.set_text(f"{width} × {height} · {refresh} Hz")
            self.preview_logical.set_text(f"Área lógica: {logical}\nPosição: {self.entries['position'].get_text()}\nWorkspace: {self.entries['workspace'].get_text()}")
        except (ValueError, InvalidOperation, ZeroDivisionError):
            self.display_summary.set_text("Preencha a resolução e a escala para ver o resumo.")
            self.preview_mode.set_text("Sua segunda tela")
            self.preview_logical.set_text("A prévia acompanha os campos do dispositivo.")
        self.preview.queue_draw()

    def _draw_display(self, _widget, cr, width, height):
        def color(value):
            cr.set_source_rgb(*(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)))
        try:
            w, h = map(int, self.entries["resolution"].get_text().split("x"))
            ratio = max(0.4, min(2.5, w / h))
        except (ValueError, ZeroDivisionError):
            ratio = 16 / 9
        screen_w = min(width - 40, (height - 34) * ratio)
        screen_h = screen_w / ratio
        x, y = (width - screen_w) / 2, (height - screen_h) / 2
        color("2E3440")
        cr.rectangle(x - 8, y - 8, screen_w + 16, screen_h + 16)
        cr.fill()
        color("88C0D0")
        cr.set_line_width(2)
        cr.rectangle(x - 8, y - 8, screen_w + 16, screen_h + 16)
        cr.stroke()
        color("434C5E")
        cr.rectangle(x, y, screen_w, screen_h)
        cr.fill()
        color("81A1C1")
        cr.rectangle(x + 10, y + 10, screen_w * .58, screen_h - 20)
        cr.fill()
        color("3B4252")
        cr.rectangle(x + screen_w * .65, y + 10, screen_w * .3 - 10, screen_h * .4)
        cr.rectangle(x + screen_w * .65, y + screen_h * .52, screen_w * .3 - 10, screen_h * .4 - 10)
        cr.fill()

    def _editor_changed(self, *_):
        if not hasattr(self, "custom_editor_box") or not hasattr(self, "editor_hint"):
            return
        editor = self.editor_ids[self.editor_dropdown.get_selected()]
        self.custom_editor_box.set_visible(editor == "custom")
        hints = {"auto": "Usa Hyprmon no Kitty, nwg-displays ou wdisplays, conforme disponível.",
                 "hyprmon": "kitty -e hyprmon", "nwg-displays": "nwg-displays", "wdisplays": "wdisplays",
                 "custom": self.custom_editor_entry.get_text().strip() or "Digite o comando acima."}
        self.editor_hint.set_text(hints[editor])

    def _tell(self, message, error=False):
        self.message.set_text(str(message))
        self.message.remove_css_class("error-text")
        if error:
            self.message.add_css_class("error-text")

    def _allow(self, capability):
        try:
            getattr(self.environment, f"require_{capability}")()
            return True
        except PipperError as exc:
            self._tell(exc, error=True)
            return False

    def _apply_environment(self, environment):
        self.environment = environment
        self.environment_label.set_text(f"{environment.desktop} · {'Wayland' if environment.wayland else 'X11 / sessão não identificada'}")
        self.compatibility_label.set_text(
            "Tela virtual disponível. As integrações abaixo acompanham os serviços ativos nesta sessão."
            if environment.hyprland else
            "O backend de tela virtual do Pipper é específico do Hyprland. Neste ambiente, use o diagnóstico e as configurações nativas disponíveis.")
        self.hypr_status.set_text("Sessão ativa · workspace configurável" if environment.hyprland else "Indisponível nesta sessão")
        self.vicinae_status.set_text("Launcher ativo nesta sessão" if environment.vicinae else "Launcher não está ativo nesta sessão")
        self.noctalia_status.set_text("Noctalia v5 ativo nesta sessão" if environment.noctalia else "Noctalia v5 não está ativo nesta sessão")
        self.noctalia_note.set_text("Salvo com backup e aplicado ao Noctalia ativo." if environment.noctalia else
                                   "Ative Noctalia v5 nesta sessão para configurar as camadas do celular.")
        if self.dependencies:
            self._dependencies(self.dependencies)

    def _refresh_environment(self, *_):
        if not self.busy and not self.closing:
            output = self.entries["output"].get_text().strip()
            def read():
                environment = detect_environment()
                exclusions = self.manager.read_exclusions(output) if environment.noctalia else None
                return environment, exclusions
            def refreshed(result):
                environment, exclusions = result
                self._apply_environment(environment)
                if exclusions is not None and output == self.entries["output"].get_text().strip():
                    self._set_switches(exclusions)
                self._tell("Ambiente e integrações atualizados.")
            self._async(read, refreshed, "Verificando serviços e ambiente…")

    def _poll_environment(self):
        if self.closing:
            return GLib.SOURCE_REMOVE
        if self.busy or getattr(self, "checking_environment", False):
            return GLib.SOURCE_CONTINUE
        self.checking_environment = True
        future = self.executor.submit(detect_environment)
        def apply():
            self.checking_environment = False
            if not self.closing and not self.busy:
                try:
                    self._apply_environment(future.result())
                    self._sensitivity()
                except Exception:
                    traceback.print_exc()
            return GLib.SOURCE_REMOVE
        future.add_done_callback(lambda _: GLib.idle_add(apply))
        return GLib.SOURCE_CONTINUE

    def _performance_changed(self, *_):
        if self.loading or self.busy or self.active_output:
            return
        profiles = {1: ("1280x720", "30", "1.0"), 2: ("1920x1080", "60", "2.0"),
                    3: ("2560x1440", "60", "2.5")}
        selected = self.performance.get_selected()
        if selected in profiles:
            for key, value in zip(("resolution", "refresh", "scale"), profiles[selected]):
                self.entries[key].set_text(value)
            self._tell("Perfil de transmissão aplicado. Você pode ajustar os campos.")

    def _rotate(self, *_):
        if self.busy or self.active_output or self.editor_process:
            return
        try:
            settings = self._get_settings()
            width, height = settings.resolution.split("x")
            self.entries["resolution"].set_text(f"{height}x{width}")
            self._tell("Orientação alterada. Ligue Pipper para usar esta configuração.")
        except PipperError as exc:
            self._tell(exc, error=True)

    def _copy_address(self, *_):
        if self.ip:
            self.get_display().get_clipboard().set(f"vnc://{self.ip}:5900")
            self._tell("Endereço VNC copiado.")

    def _copy_shortcut(self, *_):
        if self._allow("hyprland"):
            import shlex
            command = shlex.join([*command_argv(), "--toggle"])
            self.get_display().get_clipboard().set(command)
            self._tell("Comando copiado: use em um atalho do Hyprland ou botão do Noctalia.")

    def _copy_diagnostics(self, *_):
        lines = ["Pipper — diagnóstico", f"Ambiente: {self.environment.desktop}",
                 f"Wayland: {self.environment.wayland}", f"Hyprland ativo: {self.environment.hyprland}",
                 f"Noctalia v5 ativo: {self.environment.noctalia}", f"Vicinae ativo: {self.environment.vicinae}",
                 f"Servidor: {'ligado' if self.active_output else 'desligado'}",
                 f"Output: {self.entries['output'].get_text()}", f"Workspace: {self.entries['workspace'].get_text()}",
                 f"Conexão: {f'vnc://{self.ip}:5900' if self.ip else 'Sem endereço LAN'}"]
        lines.extend(f"{name}: {'disponível' if found else 'ausente'}" for name, found in self.dependencies.items())
        self.get_display().get_clipboard().set("\n".join(lines))
        self._tell("Diagnóstico copiado.")

    def _native_display(self, *_):
        self._async(lambda: open_display_settings(self.environment),
                    lambda _: self._tell("Configurações de tela abertas."))

    def _focus_phone(self, *_):
        if self._allow("hyprland"):
            self._async(lambda: self.session.focus(self.environment), self._tell, "Ativando workspace do celular…")

    def _install_vicinae(self, *_):
        if self._allow("vicinae") and self._allow("hyprland"):
            def install():
                current = detect_environment()
                paths = install_vicinae_scripts(current)
                refresh_vicinae_scripts(current)
                return paths
            self._async(install, lambda paths: self._tell(f"{len(paths)} comandos disponíveis no Vicinae. Busque Pipper no launcher."),
                        "Adicionando comandos ao Vicinae…")

    def _noctalia_action(self, action):
        if self._allow("noctalia"):
            self._async(lambda: noctalia_action(detect_environment(), action),
                        lambda _: self._tell("Ação aplicada no Noctalia."), "Aplicando ação no Noctalia…")

    def _reload_noctalia(self):
        try:
            noctalia_action(self.environment, "reload")
            return ""
        except (PipperError, OSError) as exc:
            return f" Arquivo salvo; recarga pendente: {exc}"

    def _bulk_exclusions(self, hidden):
        if not self._allow("noctalia"):
            return
        try:
            settings = self._get_settings()
        except PipperError as exc:
            self._tell(exc, error=True)
            return
        def save():
            detect_environment().require_noctalia()
            self.manager.save_exclusions(settings.output, dict.fromkeys(LAYERS, hidden))
            warning = self._reload_noctalia()
            return self.manager.read_exclusions(settings.output), warning
        def saved(result):
            exclusions, warning = result
            self._set_switches(exclusions)
            self._tell(f"Camadas {'ocultas' if hidden else 'habilitadas'} em {settings.output}." + warning)
        self._async(save, saved, "Atualizando camadas do celular…")

    def _sensitivity(self):
        available = not self.busy and not self.closing
        self.form.set_sensitive(available and not self.active_output and not self.editor_process)
        for action in self.actions:
            action.set_sensitive(available and self.environment.hyprland)
        self.power_button.set_sensitive(available and self.environment.hyprland and
                                        (bool(self.active_output) or self.dependencies.get("wayvnc", False)))
        self.entries["workspace"].set_sensitive(self.environment.hyprland)
        self.editor_button.set_sensitive(available and self.environment.hyprland and not self.editor_process)
        self.editor_form.set_sensitive(available and self.environment.hyprland and not self.editor_process)
        self.install_button.set_sensitive(available)
        can_write_noctalia = self.environment.noctalia and self.dependencies.get("python-tomlkit", False)
        for switch in self.switches.values():
            switch.set_sensitive(available and can_write_noctalia and not self.editor_process)
        for bulk in (self.hide_all_button, self.show_all_button):
            bulk.set_sensitive(available and can_write_noctalia and not self.editor_process)
        self.focus_button.set_sensitive(available and self.environment.hyprland and bool(self.active_output))
        self.shortcut_button.set_sensitive(available and self.environment.hyprland)
        self.vicinae_button.set_sensitive(available and self.environment.vicinae and self.environment.hyprland)
        self.native_display_button.set_sensitive(available and bool(self.environment.display_settings))
        for action in self.noctalia_buttons:
            action.set_sensitive(available and self.environment.noctalia)

    def _async(self, work, done=None, message=None, failed=None):
        if self.closing:
            return
        self.busy = True
        self.spinner.start()
        self._sensitivity()
        if message:
            self._tell(message)
        future = self.executor.submit(work)

        def deliver():
            self.busy = False
            self.spinner.stop()
            try:
                result = future.result()
                if done and not self.closing:
                    done(result)
            except Exception as exc:
                if not isinstance(exc, (PipperError, OSError)):
                    traceback.print_exception(exc)
                if failed:
                    failed()
                self._tell(str(exc), error=True)
            self._sensitivity()
            return GLib.SOURCE_REMOVE

        future.add_done_callback(lambda _: GLib.idle_add(deliver))

    def _get_settings(self):
        raw = MonitorSettings(**{key: entry.get_text().strip() for key, entry in self.entries.items()})
        settings, warning = raw.validated()
        self.entries["scale"].set_text(settings.scale)
        if warning:
            self._tell(warning)
        return settings

    def _set_fields(self, settings):
        for key, entry in self.entries.items():
            entry.set_text(getattr(settings, key))

    def _validate_on_leave(self, *_):
        if not self.loading and not self.busy:
            try:
                self._get_settings()
            except PipperError as exc:
                self._tell(str(exc), error=True)

    def _initial_state(self):
        environment = detect_environment()
        settings = MonitorSettings.from_preset(self.presets[0])
        notices = []
        try:
            # Prefer an explicitly saved Pipper output on subsequent launches.
            path = self.manager.hypr_path
            text = path.read_text() if path.exists() else ""
            import re
            block = re.search(r"\[PIPPER START\](.*?)\[PIPPER END\]", text, re.S)
            if block:
                match = re.search(r'output\s*=\s*["\']([\w.-]+)["\']|monitor\s*=\s*([\w.-]+),', block[1])
                if match:
                    settings = replace(settings, output=match[1] or match[2])
            settings = self.manager.read_hypr(settings)
        except (OSError, PipperError) as exc:
            notices.append(str(exc))
        try:
            if self.manager.profile_path.exists():
                settings = self.manager.read_profile()
            session_settings = self.vnc.running_settings()
            if session_settings is not None:
                settings = session_settings
        except (OSError, PipperError) as exc:
            notices.append(str(exc))
        if environment.hyprland:
            try:
                settings = self.hypr.discover(settings)
            except PipperError as exc:
                notices.append(f"Sessão Hyprland indisponível: {exc}")
        else:
            notices.append(f"{environment.desktop}: controle da tela virtual disponível em Hyprland ativo.")
        try:
            exclusions = self.manager.read_exclusions(settings.output) if environment.noctalia else dict.fromkeys(LAYERS, False)
        except (PipperError, OSError) as exc:
            notices.append(str(exc))
            exclusions = dict.fromkeys(LAYERS, False)
        try:
            preferences = self.manager.read_preferences()
        except (PipperError, OSError) as exc:
            notices.append(str(exc))
            preferences = {"editor": "auto", "custom_command": ""}
        return settings, exclusions, dependency_status(), local_addresses(), notices, self.vnc.is_running(settings.output), preferences, environment

    def _apply_initial(self, result):
        settings, exclusions, dependencies, addresses, notices, running, preferences, environment = result
        self._apply_environment(environment)
        self.loading = True
        selected = next((i for i, p in enumerate(self.presets)
                         if p["output"] == settings.output and p["resolution"] == settings.resolution), len(self.presets) - 1)
        self.dropdown.set_selected(selected)
        self._set_fields(settings)
        self._set_switches(exclusions)
        self.editor_dropdown.set_selected(self.editor_ids.index(preferences["editor"]))
        self.custom_editor_entry.set_text(preferences["custom_command"])
        self.loading = False
        if running:
            self.active_output = settings.output
        self._power_state()
        self.save_button.set_label(f"Salvar no {self.manager.hypr_path.name}")
        self._dependencies(dependencies)
        self._set_addresses(addresses)
        self._tell(" · ".join(notices) if notices else "Configurações atuais carregadas.", error=bool(notices))

    def _dependencies(self, dependencies):
        self.dependencies = dependencies
        required = (["hyprctl", "wayvnc"] if self.environment.hyprland else [])
        if self.environment.noctalia:
            required.append("python-tomlkit")
        missing = [name for name in required if not dependencies.get(name, False)]
        self.missing_dependencies = missing
        if self.environment.noctalia:
            self.noctalia_note.set_text("Salvo com backup e aplicado ao Noctalia ativo." if dependencies.get("python-tomlkit")
                                       else "Instale python-tomlkit para alterar as camadas do celular.")
        # Monitor editors are optional and individually validated when opening.
        self.warning_label.set_text("Dependências ausentes: " + ", ".join(missing))
        self.warning_box.set_visible(bool(missing))

    def _set_switches(self, exclusions):
        self.exclusion_states = {key: exclusions.get(key, False) for key in LAYERS}
        prior = self.loading
        self.loading = True
        for key, switch in self.switches.items():
            switch.set_active(exclusions.get(key, False))
        self.loading = prior

    def _preset_selected(self, *_):
        if self.loading or self.busy:
            return
        preset = self.presets[self.dropdown.get_selected()]
        settings = MonitorSettings.from_preset(preset)
        self._set_fields(settings)
        # Presets explicitly fill their documented values; initial discovery is separate.
        self.performance.set_selected(0)
        self._async(lambda: self.manager.read_exclusions(settings.output) if self.environment.noctalia else dict.fromkeys(LAYERS, False), self._set_switches,
                    "Predefinição carregada. Ajuste os campos se necessário.")

    def _output_changed(self, *_):
        if self.loading or self.busy or self.active_output:
            return
        try:
            settings = self._get_settings()
        except PipperError as exc:
            self._tell(exc, error=True)
            return
        if self.environment.noctalia:
            self._async(lambda: self.manager.read_exclusions(settings.output), self._set_switches)

    def _power_state(self):
        active = bool(self.active_output)
        self.power_button.set_label("Desligar Pipper" if active else "Ligar Pipper")
        self.power_button.remove_css_class("primary" if active else "danger")
        self.power_button.add_css_class("danger" if active else "primary")
        self.status_badge.set_text("● LIGADO" if active else "● DESLIGADO")
        if active:
            self.status_badge.add_css_class("online")
        else:
            self.status_badge.remove_css_class("online")

    def _toggle(self, *_):
        if not self._allow("hyprland"):
            return
        if self.active_output:
            output = self.active_output
            def stop():
                self.session.stop(output, self.environment)
            def stopped(_):
                self.active_output = None
                self._power_state()
                self._tell("Pipper desligado. Monitor virtual removido.")
            self._async(stop, stopped, "Desligando Pipper…")
            return
        try:
            settings = self._get_settings()
        except PipperError as exc:
            self._tell(exc, error=True)
            return

        def start():
            self.session.start(settings, self.environment)

        def started(_):
            self.active_output = settings.output
            self._power_state()
            self._tell(f"{settings.output} ligado. Conecte o celular na porta 5900.")
        self._async(start, started, "Criando tela e iniciando wayvnc…")

    def _save(self, *_):
        if not self._allow("hyprland"):
            return
        try:
            settings = self._get_settings()
        except PipperError as exc:
            self._tell(exc, error=True)
            return
        def saved(backup):
            self._tell(f"Configuração salva em {self.manager.hypr_path.name}." +
                       (f" Backup: {backup.name}" if backup else ""))
        def save():
            self.manager.save_profile(settings)
            return self.manager.save_hypr(settings)
        self._async(save, saved, "Salvando regras do Hyprland…")

    def _exclusion_changed(self, switch, _param, key):
        if self.loading or self.busy:
            return
        requested = switch.get_active()
        # GTK can defer a second notify when restoring a switch inside its
        # handler. Ignore values already matching the last known saved state.
        if requested == self.exclusion_states.get(key, False):
            return
        if not self._allow("noctalia"):
            self._set_switches(self.exclusion_states)
            return
        try:
            settings = self._get_settings()
        except PipperError as exc:
            self._set_switches(self.exclusion_states)
            self._tell(exc, error=True)
            return
        # Only mutate the selected layer; don't overwrite rules after an output rename.
        def save():
            detect_environment().require_noctalia()
            backup = self.manager.save_exclusions(settings.output, {key: requested})
            warning = self._reload_noctalia()
            return backup, self.manager.read_exclusions(settings.output), warning
        def saved(result):
            backup, exclusions, warning = result
            self._set_switches(exclusions)
            self._tell(f"{LAYERS[key]}: configuração salva para {settings.output}." +
                       (f" Backup: {backup.name}" if backup else "") + warning)
        def rollback():
            self.loading = True
            switch.set_active(not requested)
            self.loading = False
        self._async(save, saved, "Atualizando Noctalia…", failed=rollback)

    def _open_editor(self, *_):
        if not self._allow("hyprland"):
            return
        try:
            settings = self._get_settings()
        except PipperError as exc:
            self._tell(exc, error=True)
            return
        editor = self.editor_ids[self.editor_dropdown.get_selected()]
        custom = self.custom_editor_entry.get_text().strip()
        def open_selected():
            self.manager.save_preferences(editor, custom)
            return self.hypr.editor(settings, editor, custom)
        def opened(result):
            self.editor_process, created = result
            self.editor_settings = settings
            self._tell("Editor aberto. A posição será sincronizada ao fechar." +
                       (" Tela temporária criada." if created else ""))
            GLib.timeout_add(500, self._poll_editor)
        self._async(open_selected, opened, "Abrindo editor de posição…")

    def _poll_editor(self):
        if self.closing or self.editor_process is None:
            return GLib.SOURCE_REMOVE
        if self.editor_process.poll() is None or self.busy:
            return GLib.SOURCE_CONTINUE
        settings = self.editor_settings
        self.editor_process = None
        self.editor_settings = None
        self._async(lambda: self.hypr.sync(settings), self._synced, "Sincronizando posição após o editor…")
        return GLib.SOURCE_REMOVE

    def _sync(self, *_):
        if not self._allow("hyprland"):
            return
        try:
            settings = self._get_settings()
        except PipperError as exc:
            self._tell(exc, error=True)
            return
        self._async(lambda: self.hypr.sync(settings), self._synced, "Lendo posição atual…")

    def _synced(self, settings):
        self.entries["position"].set_text(settings.position)
        self.entries["scale"].set_text(settings.scale)
        self._tell(f"Posição sincronizada: {settings.position}, escala {settings.scale}. Salve para persistir.")

    def _install(self, *_):
        def launched(process):
            self._tell("Conclua a instalação no terminal. As dependências serão verificadas ao fechar.")
            GLib.timeout_add_seconds(2, poll, process)
        def poll(process):
            if self.closing:
                return GLib.SOURCE_REMOVE
            if process.poll() is None or self.busy:
                return GLib.SOURCE_CONTINUE
            self._async(dependency_status, self._dependencies)
            return GLib.SOURCE_REMOVE
        packages = [name for name in self.missing_dependencies if name in {"wayvnc", "python-tomlkit"}]
        self._async(lambda: install_dependencies(packages), launched)

    def _set_addresses(self, addresses):
        self.addresses = addresses
        self.address_dropdown.set_model(Gtk.StringList.new(addresses))
        self.address_dropdown.set_visible(len(addresses) > 1)
        self.address_dropdown.set_selected(0)
        self._set_ip(addresses[0] if addresses else None)

    def _address_changed(self, *_):
        if getattr(self, "addresses", []) and self.address_dropdown.get_selected() < len(self.addresses):
            self._set_ip(self.addresses[self.address_dropdown.get_selected()])

    def _set_ip(self, address):
        self.ip = address
        self.ip_label.set_text(address or "Sem rede local")
        self.copy_button.set_sensitive(bool(address))
        self.copy_address_button.set_sensitive(bool(address))
        self.uri_label.set_text(f"vnc://{address}:5900" if address else "Conecte o computador ao Wi-Fi ou à LAN e atualize o IP.")
        self.qr_matrix = None
        if address:
            try:
                import qrcode
                qr = qrcode.QRCode(border=4)
                qr.add_data(f"vnc://{address}:5900")
                qr.make(fit=True)
                self.qr_matrix = qr.get_matrix()
            except ImportError:
                pass
        self.qr.set_visible(self.qr_matrix is not None)
        self.qr.queue_draw()

    def _draw_qr(self, _widget, cr, width, height):
        if not self.qr_matrix:
            return
        # High contrast within the required Nord palette, integer module sizing.
        size = len(self.qr_matrix)
        unit = max(1, min(width, height) // size)
        cr.set_source_rgb(236 / 255, 239 / 255, 244 / 255)
        cr.paint()
        cr.set_source_rgb(46 / 255, 52 / 255, 64 / 255)
        ox, oy = (width - size * unit) // 2, (height - size * unit) // 2
        for y, row in enumerate(self.qr_matrix):
            for x, dark in enumerate(row):
                if dark:
                    cr.rectangle(ox + x * unit, oy + y * unit, unit, unit)
        cr.fill()

    def _copy_ip(self, *_):
        if self.ip:
            self.get_display().get_clipboard().set(self.ip)
            self._tell("IP copiado para a área de transferência.")

    def _refresh_ip(self, *_):
        if not self.busy:
            self._async(local_addresses, self._set_addresses, "Atualizando endereços de rede…")

    def _poll_vnc(self):
        if self.closing:
            return GLib.SOURCE_REMOVE
        if self.active_output and not self.busy and self.vnc.process and self.vnc.process.poll() is not None:
            if self.status_badge.get_text() != "● VNC ENCERRADO":
                self.status_badge.set_text("● VNC ENCERRADO")
                self.status_badge.remove_css_class("online")
                self._tell(f"wayvnc encerrou. Desligue Pipper e consulte {self.vnc.log_path} antes de tentar novamente.", error=True)
        if not self.busy and not getattr(self, "checking_session", False) and self.environment.hyprland:
            self.checking_session = True
            def read():
                settings = self.session.settings()
                return settings, self.vnc.is_running(settings.output)
            future = self.executor.submit(read)
            def apply():
                self.checking_session = False
                if self.closing or self.busy:
                    return GLib.SOURCE_REMOVE
                try:
                    settings, running = future.result()
                    output = settings.output if running else None
                    if output != self.active_output:
                        self.active_output = output
                        if running:
                            self.loading = True
                            self._set_fields(settings)
                            selected = next((i for i, p in enumerate(self.presets)
                                             if p["output"] == settings.output and p["resolution"] == settings.resolution), len(self.presets) - 1)
                            self.dropdown.set_selected(selected)
                            self.loading = False
                        self._power_state()
                        self._sensitivity()
                        self._tell("Sessão atualizada pelo atalho/launcher." if running else "Sessão encerrada pelo atalho/launcher ou pelo servidor.")
                except (PipperError, OSError) as exc:
                    self._tell(exc, error=True)
                return GLib.SOURCE_REMOVE
            future.add_done_callback(lambda _: GLib.idle_add(apply))
        return GLib.SOURCE_CONTINUE

    def _close_requested(self, *_):
        if self.closing:
            return True
        self.closing = True
        self._sensitivity()
        self._tell("Fechando a janela. A sessão ativa continuará funcionando…")
        app = self.get_application()
        app.hold()
        def cleanup():
            errors = []
            output = self.active_output or self.vnc.output
            targets = set(self.hypr.temporary_outputs)
            for target in targets:
                if not self.environment.hyprland:
                    continue
                if target == output or self.vnc.is_running(target):
                    continue
                try:
                    self.hypr.remove_output(target)
                except Exception as exc:
                    errors.append(str(exc))
            return errors
        future = self.executor.submit(cleanup)
        def finished():
            errors = future.result()
            if errors:
                print("Pipper: " + "; ".join(errors), file=sys.stderr)
            self.executor.shutdown(wait=False)
            self.destroy()
            app.release()
            return GLib.SOURCE_REMOVE
        future.add_done_callback(lambda _: GLib.idle_add(finished))
        return True


class PipperApplication(Gtk.Application):
    def __init__(self):
        # Gio requires a dotted D-Bus ID. The Wayland surface gets 'pipper'
        # explicitly on realize, independently of this D-Bus application ID.
        super().__init__(application_id="io.github.pipper.Pipper", flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.window = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_search_path(str(data_directory() / "icons"))
        Gtk.Window.set_default_icon_name("pipper")
        provider = Gtk.CssProvider()
        provider.load_from_path(str(ASSETS / "style.css"))
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.css_provider = provider

    def do_activate(self):
        if self.window is None:
            self.window = PipperWindow(self)
        self.window.present()


def main():
    GLib.set_prgname("pipper")
    GLib.set_application_name("Pipper")
    return PipperApplication().run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Capture native GTK tutorial screens with simulated services and temporary settings.

Run: xvfb-run -a env GDK_BACKEND=x11 GSK_RENDERER=cairo python3 scripts/capture_tutorial.py
"""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]


def main():
    with tempfile.TemporaryDirectory(prefix='pipper-docs-') as directory:
        os.environ.update(XDG_CONFIG_HOME=directory, XDG_STATE_HOME=directory,
                          NOCTALIA_CONFIG_HOME=directory, GTK_THEME='Adwaita:dark')
        from src.main import PipperApplication
        from src.config_manager import HyprlandController
        from src.integrations import Environment
        from test_config_manager import FakeHypr
        from gi.repository import Gio, GLib, Gtk

        app = PipperApplication()
        app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
        tabs = iter(('device', 'position', 'appearance', 'integrations'))
        pending = [None]
        errors = []
        output = ROOT / 'docs/images'
        output.mkdir(parents=True, exist_ok=True)

        def advance():
            if app.window is None or app.window.busy:
                return GLib.SOURCE_CONTINUE
            window = app.window
            try:
                if pending[0]:
                    paintable = Gtk.WidgetPaintable.new(window)
                    snapshot = Gtk.Snapshot()
                    paintable.snapshot(snapshot, window.get_width(), window.get_height())
                    texture = window.get_renderer().render_texture(snapshot.to_node(), None)
                    assert texture.save_to_png(str(output / pending[0]))
                    print('Captured', pending[0], flush=True)
                tab = next(tabs, None)
                if tab is None:
                    window.close()
                    return GLib.SOURCE_REMOVE
                window.set_default_size(1040, 1540 if tab == 'integrations' else 1120)
                window.editor_dropdown.set_selected(window.editor_ids.index('hyprmon'))
                window.tabs.set_visible_child_name(tab)
                pending[0] = {'device': '01-device.png', 'position': '02-position.png',
                              'appearance': '03-appearance.png', 'integrations': '04-integrations.png'}[tab]
            except Exception as exc:
                errors.append(exc)
                app.quit()
                return GLib.SOURCE_REMOVE
            return GLib.SOURCE_CONTINUE

        def timeout():
            errors.append(RuntimeError('Capture timed out'))
            app.quit()
            return GLib.SOURCE_REMOVE

        with patch('src.main.HyprlandController', lambda: HyprlandController(FakeHypr(), lambda _: None)), \
             patch('src.main.WayVNCManager.is_running', return_value=False), \
             patch('src.main.detect_environment', return_value=Environment('Hyprland', True, True, True, True)), \
             patch('src.main.dependency_status', return_value=dict.fromkeys(
                 ['hyprctl', 'wayvnc', 'nwg-displays', 'wdisplays', 'python-tomlkit'], True)), \
             patch('src.main.local_addresses', return_value=['192.168.1.42']):
            GLib.timeout_add(750, advance)
            GLib.timeout_add_seconds(20, timeout)
            app.run([])
        if app.window:
            app.window.executor.shutdown(wait=True)
        if errors:
            raise errors[0]


if __name__ == '__main__':
    main()

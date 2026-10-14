"""UI integration gates across desktop sessions; no real service is invoked."""
from pathlib import Path
import faulthandler
import os
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_config_manager import FakeHypr

temporary = tempfile.TemporaryDirectory(prefix="pipper-environments-")
root = Path(temporary.name)
for key, directory in (("XDG_CONFIG_HOME", "config"), ("NOCTALIA_CONFIG_HOME", "config"),
                       ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state")):
    os.environ[key] = str(root / directory)
os.environ["GTK_THEME"] = "Adwaita:dark"

from src.main import PipperApplication
from src.config_manager import HyprlandController
from src.integrations import Environment
from gi.repository import Gio, GLib

scenarios = [Environment("GNOME", True, display_settings=("gnome-control-center", "display")),
             Environment("KDE Plasma", True, display_settings=("systemsettings", "kcm_kscreen")),
             Environment("Sway", True), Environment("Niri", True), Environment("Desconhecido"),
             Environment("Hyprland", True, True),
             Environment("GNOME", True, False, False, True, ("gnome-control-center", "display")),
             Environment("Hyprland", True, True, True, True)]
failures = []


def run_scenario(env):
    faulthandler.dump_traceback_later(15, exit=True)
    fake = FakeHypr()
    app = PipperApplication()
    app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
    stage = [0]

    def advance():
        window = app.window
        if window is None or window.busy:
            return GLib.SOURCE_CONTINUE
        try:
            if stage[0] == 0:
                assert window.power_button.get_sensitive() == env.hyprland
                assert window.save_button.get_sensitive() == env.hyprland
                assert window.editor_button.get_sensitive() == env.hyprland
                assert window.entries["workspace"].get_sensitive() == env.hyprland
                assert window.native_display_button.get_sensitive() == bool(env.display_settings)
                assert window.vicinae_button.get_sensitive() == bool(env.hyprland and env.vicinae)
                assert all(switch.get_sensitive() == env.noctalia for switch in window.switches.values())
                assert all(b.get_sensitive() == env.noctalia for b in window.noctalia_buttons)
                if not env.hyprland:
                    window._toggle()
                    window._save()
                    window._open_editor()
                    window._sync()
                    assert not fake.calls
                    assert not window.manager.profile_path.exists()
                if not env.noctalia:
                    window._bulk_exclusions(True)
                    window.switches["dock"].set_active(True)
                    assert not window.switches["dock"].get_active()
                    assert not window.manager.noctalia_path.exists()
                if env.hyprland and env.vicinae:
                    window.entries["workspace"].set_text("0")
                    window.switches["dock"].set_active(True)
                    assert not window.switches["dock"].get_active()
                    assert not window.manager.noctalia_path.exists()
                    window.entries["workspace"].set_text("11")
                    window.performance.set_selected(1)
                    assert window.entries["resolution"].get_text() == "1280x720"
                    assert window.entries["refresh"].get_text() == "30"
                    window._rotate()
                    assert window.entries["resolution"].get_text() == "720x1280"
                    window._install_vicinae()
                stage[0] += 1
            elif stage[0] == 1:
                if env.hyprland and env.vicinae:
                    assert len(list((root / "data/vicinae/scripts").glob("pipper-*.py"))) == 4
                    window._bulk_exclusions(True)
                stage[0] += 1
            elif stage[0] == 2:
                if env.noctalia:
                    assert all(window.manager.read_exclusions("S22").values())
                    assert all(switch.get_active() for switch in window.switches.values())
                    window.tabs.set_visible_child_name("integrations")
                    window.set_default_size(1050, 1100)
                stage[0] += 1
            else:
                if env.noctalia and len(sys.argv) > 1:
                    import gi
                    gi.require_version("Gsk", "4.0")
                    from gi.repository import Gtk
                    snapshot = Gtk.Snapshot()
                    Gtk.WidgetPaintable.new(window).snapshot(snapshot, window.get_width(), window.get_height())
                    texture = window.get_renderer().render_texture(snapshot.to_node(), None)
                    assert texture.save_to_png(sys.argv[1])
                print("GTK environment:", env.desktop, "Noctalia:", env.noctalia, "Vicinae:", env.vicinae, "OK", flush=True)
                window.close()
                return GLib.SOURCE_REMOVE
        except Exception as exc:
            failures.append(exc)
            import traceback
            traceback.print_exc()
            app.quit()
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    with patch("src.main.detect_environment", return_value=env), \
         patch("src.main.refresh_vicinae_scripts", return_value=[]), \
         patch("src.main.noctalia_action", return_value="ok"), \
         patch("src.main.HyprlandController", lambda: HyprlandController(fake, lambda _: None)), \
         patch("src.main.WayVNCManager.is_running", return_value=False), \
         patch("src.main.local_addresses", return_value=["192.168.1.42"]), \
         patch("src.main.dependency_status", return_value=dict.fromkeys(
             ["hyprctl", "wayvnc", "nwg-displays", "wdisplays", "python-tomlkit"], True)):
        timer = GLib.timeout_add_seconds(10, lambda: app.quit() or GLib.SOURCE_REMOVE)
        GLib.timeout_add(250, advance)
        app.run([])
        GLib.source_remove(timer)
        if app.window:
            app.window.executor.shutdown(wait=True)
    assert stage[0] == 3 and not failures
    faulthandler.cancel_dump_traceback_later()


try:
    for environment in scenarios:
        run_scenario(environment)
finally:
    temporary.cleanup()
print("GTK environment gates passed")

"""Run with xvfb-run; uses only temporary files and a fake compositor/VNC."""
from pathlib import Path
import json
import os
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
temporary = tempfile.TemporaryDirectory(prefix="pipper-gtk-")
root = Path(temporary.name)
os.environ["XDG_CONFIG_HOME"] = str(root / "config")
os.environ["XDG_STATE_HOME"] = str(root / "state")
os.environ["NOCTALIA_CONFIG_HOME"] = str(root / "config")
os.environ["GTK_THEME"] = "Adwaita:dark"

from unittest.mock import patch
from unittest.mock import Mock
from src.main import PipperApplication
from src.config_manager import HyprlandController, MonitorSettings
from src.integrations import Environment
from test_config_manager import FakeHypr
from gi.repository import Gio, GLib

fake = FakeHypr()
steps = []
failures = []
app = PipperApplication()
app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
editor_child = Mock()
editor_child.poll.return_value = None
editor_spawn = Mock(return_value=editor_child)
running = set()


def fake_start(manager, settings):
    manager.output = settings.output
    manager.state_dir.mkdir(parents=True, exist_ok=True)
    manager.session_path.write_text(json.dumps(settings.__dict__))
    running.add(settings.output)


def fake_stop(manager, output):
    running.discard(output)
    manager._forget_session(output)
    manager.output = None


def later(action):
    steps.append(action)


def check_initial():
    window = app.window
    assert window.dropdown.get_selected() == 0
    assert window.entries["output"].get_text() == "S22"
    assert window.entries["position"].get_text() == "3552x1376"
    assert not window.switches["dock"].get_active()
    assert not window.get_titlebar().get_show_title_buttons()
    assert window.dropdown.get_enable_search()
    window.dropdown.set_selected(1)


def check_native():
    window = app.window
    assert window.entries["resolution"].get_text() == "2340x1080"
    window.entries["scale"].set_text("3.5")
    window._validate_on_leave()
    assert window.entries["scale"].get_text() == "3.6"
    assert "ajustada" in window.message.get_text()
    window.dropdown.set_selected(0)


def choose_new_device():
    window = app.window
    index = next(i for i, preset in enumerate(window.presets) if preset["output"] == "MotoEdge")
    window.dropdown.set_selected(index)


def check_new_device():
    window = app.window
    assert window.entries["output"].get_text() == "MotoEdge"
    assert window.entries["resolution"].get_text() == "1920x1080"
    assert "1920" in window.display_summary.get_text()
    window.dropdown.set_selected(0)


def toggle_exclusion():
    app.window.tabs.set_visible_child_name("appearance")
    app.window.switches["dock"].set_active(True)


def check_exclusion_and_save():
    window = app.window
    assert window.manager.read_exclusions("S22")["dock"]
    assert window.switches["dock"].get_active()
    window._save()


def check_saved_and_start():
    window = app.window
    assert "[PIPPER START]" in window.manager.hypr_path.read_text()
    assert window.manager.read_hypr(MonitorSettings()).position == "3552x1376"
    window._toggle()


def check_running_and_sync():
    window = app.window
    assert window.active_output == "S22"
    assert window.power_button.get_label() == "Desligar Pipper"
    assert not window.form.get_sensitive()
    window.set_default_size(1000, 850)
    window.tabs.set_visible_child_name("device")
    fake.outputs[0].update(x=3552, y=1376)
    window._sync()


def capture(name):
    window = app.window
    if len(sys.argv) > 1:
        import gi
        gi.require_version("Gsk", "4.0")
        from gi.repository import Gtk
        paintable = Gtk.WidgetPaintable.new(window)
        snapshot = Gtk.Snapshot()
        paintable.snapshot(snapshot, window.get_width(), window.get_height())
        node = snapshot.to_node()
        texture = window.get_renderer().render_texture(node, None)
        path = Path(sys.argv[1])
        if name:
            path = path.with_name(path.stem + "-" + name + path.suffix)
        assert texture.save_to_png(str(path))


def screenshot_and_stop():
    window = app.window
    assert window.entries["position"].get_text() == "3552x1376"
    capture("")
    window._toggle()


def check_stopped_and_open_hyprmon():
    window = app.window
    assert window.active_output is None
    assert window.power_button.get_label() == "Ligar Pipper"
    assert fake.outputs == []
    assert window.form.get_sensitive()
    window.tabs.set_visible_child_name("position")
    window.editor_dropdown.set_selected(window.editor_ids.index("hyprmon"))
    assert window.editor_hint.get_text() == "kitty -e hyprmon"
    assert not window.custom_editor_box.get_visible()
    window._open_editor()


def check_editor_and_finish():
    window = app.window
    editor_spawn.assert_called_once_with(["kitty", "-e", "hyprmon"])
    assert window.editor_process is editor_child
    assert "S22" in window.hypr.temporary_outputs
    assert not window.editor_form.get_sensitive()
    assert window.manager.read_preferences()["editor"] == "hyprmon"
    editor_child.poll.return_value = 0
    window._poll_editor()


def check_editor_synced():
    window = app.window
    assert window.entries["position"].get_text() == "20x30"
    assert window.editor_process is None
    assert window.editor_form.get_sensitive()
    capture("position")
    window.editor_dropdown.set_selected(window.editor_ids.index("custom"))
    window.custom_editor_entry.set_text('foot -e "/opt/my editor"')
    assert window.custom_editor_box.get_visible()
    assert "foot" in window.editor_hint.get_text()
    editor_child.poll.return_value = None
    window._open_editor()


def check_custom_editor():
    window = app.window
    editor_spawn.assert_called_with(["foot", "-e", "/opt/my editor"])
    preferences = window.manager.read_preferences()
    assert preferences["editor"] == "custom"
    assert preferences["custom_command"] == 'foot -e "/opt/my editor"'
    editor_child.poll.return_value = 0
    window._poll_editor()


def show_appearance():
    window = app.window
    assert window.editor_process is None
    window.tabs.set_visible_child_name("appearance")


def check_tabs_and_close():
    assert app.window.tabs.get_visible_child_name() == "appearance"
    capture("appearance")
    window = app.window
    window.close()


for step in (check_initial, check_native, choose_new_device, check_new_device, toggle_exclusion, check_exclusion_and_save,
             check_saved_and_start, check_running_and_sync, screenshot_and_stop,
             check_stopped_and_open_hyprmon, check_editor_and_finish, check_editor_synced, check_custom_editor,
             show_appearance, check_tabs_and_close):
    later(step)


def advance():
    if app.window is None or app.window.busy:
        return GLib.SOURCE_CONTINUE
    if not steps:
        return GLib.SOURCE_REMOVE
    step = steps.pop(0)
    try:
        step()
        print("GTK:", step.__name__, "OK", flush=True)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        failures.append(exc)
        app.quit()
        return GLib.SOURCE_REMOVE
    return GLib.SOURCE_CONTINUE


def timeout():
    failures.append(AssertionError("GTK smoke timed out"))
    app.quit()
    return GLib.SOURCE_REMOVE


with patch("src.main.HyprlandController", lambda: HyprlandController(fake, lambda _: None)), \
     patch("src.main.WayVNCManager.is_running", lambda self, output: output in running), \
     patch("src.main.WayVNCManager.start", fake_start), patch("src.main.WayVNCManager.stop", fake_stop), \
     patch("src.main.detect_environment", return_value=Environment("Hyprland", True, True, True, True)), \
     patch("src.main.noctalia_action", return_value="ok"), \
     patch("src.main.dependency_status", return_value=dict.fromkeys(
         ["hyprctl", "wayvnc", "nwg-displays", "wdisplays", "python-tomlkit"], True)), \
     patch("src.main.local_addresses", return_value=["192.168.1.42"]):
    with patch("src.config_manager.shutil.which", return_value="/usr/bin/editor"), \
         patch("src.config_manager.subprocess.Popen", editor_spawn):
        GLib.timeout_add(450, advance)
        GLib.timeout_add_seconds(20, timeout)
        app.run([])

if app.window:
    app.window.executor.shutdown(wait=True)
temporary.cleanup()
if failures or steps:
    raise SystemExit(1)
print("GTK workflow smoke passed")

"""Regression: close, recover an unsaved device, stop, and close during startup."""
from pathlib import Path
import json
import os
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_config_manager import FakeHypr

temporary = tempfile.TemporaryDirectory(prefix="pipper-lifecycle-")
root = Path(temporary.name)
for key in ("XDG_CONFIG_HOME", "NOCTALIA_CONFIG_HOME"):
    os.environ[key] = str(root / "config")
os.environ["XDG_STATE_HOME"] = str(root / "state")
os.environ["GTK_THEME"] = "Adwaita:dark"

from src.main import PipperApplication
from src.config_manager import HyprlandController, WayVNCManager, MonitorSettings
from src.integrations import Environment
from gi.repository import Gio, GLib

fake = FakeHypr()
running = set()
errors = []


def fake_start(manager, settings):
    manager.output = settings.output
    manager.state_dir.mkdir(parents=True, exist_ok=True)
    manager.session_path.write_text(json.dumps(settings.__dict__))
    running.add(settings.output)


def fake_stop(manager, output):
    running.discard(output)
    manager._forget_session(output)
    manager.output = None


def run_window(steps):
    app = PipperApplication()
    app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
    actions = iter(steps)

    def advance():
        if app.window is None or app.window.busy:
            return GLib.SOURCE_CONTINUE
        try:
            action = next(actions)
        except StopIteration:
            return GLib.SOURCE_REMOVE
        try:
            action(app.window)
        except Exception as exc:
            errors.append(exc)
            import traceback
            traceback.print_exc()
            app.quit()
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    timeout = GLib.timeout_add_seconds(15, lambda: app.quit() or GLib.SOURCE_REMOVE)
    GLib.timeout_add(150, advance)
    app.run([])
    GLib.source_remove(timeout)
    if app.window:
        app.window.executor.shutdown(wait=True)
    assert not errors


def start_custom(window):
    assert window.active_output is None
    window.entries["output"].set_text("PocketDisplay")
    window.entries["workspace"].set_text("17")
    window._toggle()


def close_active(window):
    assert window.active_output == "PocketDisplay"
    # Navigate elsewhere before closing: the configured target must survive.
    fake.outputs[0]["activeWorkspace"] = {"id": 23}
    window.close()


def recover_and_stop(window):
    assert window.active_output == "PocketDisplay"
    assert window.entries["output"].get_text() == "PocketDisplay"
    assert window.entries["workspace"].get_text() == "17"
    assert window.power_button.get_label() == "Desligar Pipper"
    window._toggle()


def close_stopped(window):
    assert window.active_output is None
    assert not running
    assert not fake.outputs
    window.close()


def close_while_starting(window):
    window.entries["output"].set_text("DuringStartup")
    window._toggle()
    assert window.busy
    window.close()


def external_stop(window):
    assert window.active_output == "DuringStartup"
    fake_stop(window.vnc, "DuringStartup")
    window.hypr.remove_output("DuringStartup")
    window._poll_vnc()


def external_start(window):
    assert window.active_output is None
    window.session.start(MonitorSettings(output="LauncherDisplay", workspace="11"), window.environment)
    window._poll_vnc()


def check_external_session(window):
    assert window.active_output == "LauncherDisplay"
    assert window.entries["output"].get_text() == "LauncherDisplay"
    assert window.entries["workspace"].get_text() == "11"
    assert window.focus_button.get_sensitive()
    window._toggle()


try:
    with patch("src.main.HyprlandController", lambda: HyprlandController(fake, lambda _: None)), \
         patch("src.main.detect_environment", return_value=Environment("Hyprland", True, True, True, True)), \
         patch("src.main.noctalia_action", return_value="ok"), \
         patch("src.main.WayVNCManager.is_running", lambda self, output: output in running), \
         patch("src.main.WayVNCManager.start", fake_start), \
         patch("src.main.WayVNCManager.stop", autospec=True, side_effect=fake_stop) as stop, \
         patch("src.main.dependency_status", return_value=dict.fromkeys(
             ["hyprctl", "wayvnc", "nwg-displays", "wdisplays", "python-tomlkit"], True)), \
         patch("src.main.local_addresses", return_value=["192.168.1.42"]):
        run_window([start_custom, close_active])
        assert "PocketDisplay" in running
        assert any(m["name"] == "PocketDisplay" for m in fake.outputs)
        stop.assert_not_called()
        print("GTK: closing preserves active VNC and virtual output")
        run_window([recover_and_stop, close_stopped])
        assert stop.call_count == 1
        print("GTK: reopening recovers unsaved output; explicit stop ends session")
        run_window([close_while_starting])
        assert "DuringStartup" in running
        assert any(m["name"] == "DuringStartup" for m in fake.outputs)
        assert stop.call_count == 1
        print("GTK: closing during startup also preserves session")
        run_window([external_stop, external_start, check_external_session, close_stopped])
        assert stop.call_count == 2
        print("GTK: UI follows external launcher stop/start and preserves workspace")
finally:
    temporary.cleanup()
print("GTK lifecycle passed")

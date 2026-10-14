import ast
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from src import cli
from src.config_manager import ConfigManager, HyprlandController, MonitorSettings, PipperError, WayVNCManager
from src.integrations import Environment, detect_environment, install_vicinae_scripts, noctalia_action, open_display_settings, running_in_session, refresh_vicinae_scripts
from src.session import Session
from test_config_manager import FakeHypr


class EnvironmentTests(unittest.TestCase):
    def test_process_must_belong_to_the_same_display(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            process = root / "123"
            process.mkdir()
            (process / "comm").write_text("vicinae\n")
            (process / "environ").write_bytes(b"WAYLAND_DISPLAY=wayland-1\0XDG_RUNTIME_DIR=/run/user/1000\0")
            env = {"WAYLAND_DISPLAY": "wayland-1", "DISPLAY": ":0", "XDG_RUNTIME_DIR": "/run/user/1000"}
            with patch("src.integrations.Path", return_value=root):
                self.assertTrue(running_in_session("vicinae", env))
                self.assertFalse(running_in_session("noctalia", env))
                env["WAYLAND_DISPLAY"] = "wayland-2"
                self.assertFalse(running_in_session("vicinae", env))
                self.assertFalse(running_in_session("vicinae", {"XDG_RUNTIME_DIR": "/run/user/1000"}))
                env.update(WAYLAND_DISPLAY="wayland-1", XDG_SESSION_TYPE="x11")
                self.assertFalse(running_in_session("vicinae", env))

    def detect(self, desktop="Hyprland", session="wayland", live=True, version="noctalia v5.0.0", processes=True):
        env = {"XDG_CURRENT_DESKTOP": desktop, "XDG_SESSION_TYPE": session,
               "WAYLAND_DISPLAY": "wayland-1", "HYPRLAND_INSTANCE_SIGNATURE": "test"}
        def runner(args, **kwargs):
            if not live:
                raise PipperError("Not running")
            if args[0] == "hyprctl":
                return "[]"
            if args[0] == "noctalia":
                return version if "--version" in args else '{"running":true}'
            return "pong"
        return detect_environment(env, runner, lambda _: "/bin/program", lambda *_: processes)

    def test_installed_programs_are_not_active_integrations(self):
        env = self.detect(processes=False, live=False)
        self.assertFalse(env.hyprland)
        self.assertFalse(env.noctalia)
        self.assertFalse(env.vicinae)

    def test_vicinae_server_process_name_is_recognized_without_accepting_helpers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            process = root / "123"
            process.mkdir()
            (process / "comm").write_text("vicinae-server\n")
            (process / "environ").write_bytes(b"WAYLAND_DISPLAY=wayland-1\0")
            env = {"WAYLAND_DISPLAY": "wayland-1"}
            with patch("src.integrations.Path", wraps=Path) as path_class:
                path_class.side_effect = lambda value: root if value == "/proc" else Path(value)
                self.assertTrue(running_in_session("vicinae", env))
                (process / "comm").write_text("QtMainThread\n")
                (process / "cmdline").write_bytes(b"/usr/bin/vicinae-server\0{}\0")
                self.assertTrue(running_in_session("vicinae", env))
                (process / "comm").write_text("vicinae-file-in\n")
                (process / "cmdline").write_bytes(b"/usr/libexec/vicinae/vicinae-file-indexer\0")
                self.assertFalse(running_in_session("vicinae", env))

    def test_vicinae_reload_verifies_all_commands_after_rescan(self):
        names = ["Pipper — Ligar ou desligar", "Pipper — Workspace do celular",
                 "Pipper — Conexão e status", "Pipper — Abrir aplicativo"]
        commands = [{"id": f"script:{i}", "name": name} for i, name in enumerate(names)]
        runner = Mock(side_effect=["ok", "[]", json.dumps(commands)])
        pause = Mock()
        result = refresh_vicinae_scripts(Environment("Hyprland", True, True, False, True), runner, pause)
        self.assertEqual(result, commands)
        self.assertEqual(runner.call_args_list[0].args[0], ["vicinae", "cmd", "launch", "core:reload-scripts"])
        pause.assert_called_once_with(.2)

    def test_vicinae_reload_reports_missing_index_entries(self):
        runner = Mock(return_value="[]")
        with self.assertRaisesRegex(PipperError, "quatro comandos"):
            refresh_vicinae_scripts(Environment("Hyprland", True, True, False, True), runner, lambda _: None)

    def test_hyprland_requires_wayland_and_working_ipc(self):
        self.assertTrue(self.detect().hyprland)
        self.assertFalse(self.detect(session="x11").hyprland)
        self.assertFalse(self.detect(live=False).hyprland)

    def test_other_desktops_do_not_use_leftover_hyprland_variables(self):
        for desktop in ("GNOME", "KDE", "sway", "niri"):
            with self.subTest(desktop=desktop):
                self.assertFalse(self.detect(desktop).hyprland)

    def test_noctalia_v4_is_not_treated_as_v5(self):
        self.assertFalse(self.detect(version="noctalia v4.9.0").noctalia)
        self.assertTrue(self.detect().noctalia)

    def test_native_display_program_depends_on_current_desktop(self):
        self.assertEqual(self.detect("GNOME").display_settings, ("gnome-control-center", "display"))
        self.assertEqual(self.detect("KDE").display_settings, ("systemsettings", "kcm_kscreen"))
        self.assertEqual(self.detect("Hyprland").display_settings, ())

    def test_disabled_native_settings_never_launch(self):
        with patch("src.integrations.subprocess.Popen") as spawn, self.assertRaises(PipperError):
            open_display_settings(Environment("Hyprland", True, True))
        spawn.assert_not_called()

    def test_noctalia_guards_and_allowlist(self):
        runner = Mock(return_value="ok")
        with self.assertRaises(PipperError):
            noctalia_action(Environment(), "reload", runner)
        runner.assert_not_called()
        current = Environment("Hyprland", True, True, True)
        noctalia_action(current, "reload", runner)
        self.assertEqual(runner.call_args.args[0], ["noctalia", "msg", "config-reload"])
        with self.assertRaises(PipperError):
            noctalia_action(current, "session shutdown", runner)

    def test_vicinae_scripts_are_executable_safe_and_idempotent(self):
        with tempfile.TemporaryDirectory(prefix="Pipper's ") as directory:
            root = Path(directory)
            launcher = root / "project with spaces/pipper"
            env = Environment("Hyprland", True, True, False, True)
            paths = install_vicinae_scripts(env, launcher, root)
            self.assertEqual(len(paths), 4)
            for path in paths:
                content = path.read_text()
                ast.parse(content)
                self.assertIn("@vicinae.schemaVersion 1", content)
                self.assertTrue(path.stat().st_mode & 0o100)
                self.assertNotIn("shell=True", content)
            self.assertEqual(paths, install_vicinae_scripts(env, launcher, root))
            self.assertEqual(list(root.rglob("*.bak")), [])

    def test_vicinae_install_rejected_without_active_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(PipperError):
                install_vicinae_scripts(Environment("GNOME", True, False, False, True), Path("/tmp/pipper"), Path(directory))
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_vicinae_updates_keep_backups_outside_script_index(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = Environment("Hyprland", True, True, False, True)
            launcher = root / "project/pipper"
            paths = install_vicinae_scripts(env, launcher, root)
            paths[0].write_text(paths[0].read_text() + "# old version\n")
            legacy = paths[1].with_name(paths[1].name + ".pipper-old.bak")
            legacy.write_text(paths[1].read_text())
            install_vicinae_scripts(env, launcher, root)
            self.assertEqual(len(list((root / "pipper/vicinae-backups").glob("*.bak"))), 2)
            self.assertEqual(len(list(paths[0].parent.iterdir())), 4)
            self.assertFalse(any(path.name.endswith(".bak") for path in paths[0].parent.iterdir()))


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.manager = ConfigManager(root / "config")
        self.fake = FakeHypr()
        self.vnc = WayVNCManager(root / "state")
        self.running = set()
        self.vnc.is_running = lambda output: output in self.running
        def start(settings):
            self.running.add(settings.output)
            self.vnc.session_path.write_text(json.dumps(settings.__dict__))
        def stop(output):
            self.running.discard(output)
            self.vnc._forget_session(output)
        self.vnc.start = Mock(side_effect=start)
        self.vnc.stop = Mock(side_effect=stop)
        self.session = Session(self.manager, HyprlandController(self.fake, lambda _: None), self.vnc)
        self.env = Environment("Hyprland", True, True)

    def tearDown(self):
        self.temporary.cleanup()

    def test_cli_toggle_retains_last_profile_after_stopping(self):
        settings = MonitorSettings(output="CustomPhone", workspace="17")
        self.session.start(settings, self.env)
        self.assertIn("CustomPhone", self.running)
        self.session.toggle(self.env)
        self.assertFalse(self.running)
        self.assertEqual(self.manager.read_profile(), settings)
        self.session.toggle(self.env)
        self.assertIn("CustomPhone", self.running)
        self.assertEqual(self.session.settings().workspace, "17")

    def test_start_does_not_restart_an_already_active_server(self):
        self.session.start(MonitorSettings(), self.env)
        calls = len(self.fake.calls)
        self.session.start(MonitorSettings(), self.env)
        self.assertEqual(self.vnc.start.call_count, 1)
        self.assertEqual(len(self.fake.calls), calls)

    def test_another_device_requires_stopping_current_session(self):
        self.session.start(MonitorSettings(), self.env)
        with self.assertRaises(PipperError):
            self.session.start(MonitorSettings(output="OtherPhone"), self.env)
        self.assertEqual(self.running, {"S22"})

    def test_environment_guard_precedes_all_mutations(self):
        other = Environment("GNOME", True)
        for action in (lambda: self.session.start(MonitorSettings(), other),
                       lambda: self.session.stop("S22", other), lambda: self.session.toggle(other),
                       lambda: self.session.focus(other)):
            with self.assertRaises(PipperError):
                action()
        self.assertEqual(self.fake.calls, [])
        self.assertFalse(self.manager.profile_path.exists())

    def test_focus_only_uses_target_workspace_while_running(self):
        with self.assertRaises(PipperError):
            self.session.focus(self.env)
        self.session.start(MonitorSettings(workspace="17"), self.env)
        self.session.focus(self.env)
        self.assertIn('workspace = "17"', self.fake.calls[-1][-1])

    def test_failed_start_rolls_back_new_output(self):
        self.vnc.start.side_effect = PipperError("port busy")
        with self.assertRaises(PipperError):
            self.session.start(MonitorSettings(), self.env)
        self.assertFalse(self.fake.outputs)

    def test_cli_json_status_does_not_mutate_session(self):
        stdout = io.StringIO()
        with patch("src.cli.detect_environment", return_value=self.env), \
             patch("src.cli.Session", return_value=self.session), \
             patch("src.cli.local_addresses", return_value=["192.168.1.7"]), \
             contextlib.redirect_stdout(stdout):
            self.assertEqual(cli.main(["--status", "--json"]), 0)
        status = json.loads(stdout.getvalue())
        self.assertEqual(status["workspace"], "11")
        self.assertEqual(status["addresses"], ["vnc://192.168.1.7:5900"])
        self.assertFalse(self.fake.calls)

    def test_cli_rejects_mutation_in_unsupported_environment(self):
        stderr = io.StringIO()
        with patch("src.cli.detect_environment", return_value=Environment("GNOME", True)), \
             patch("src.cli.Session", return_value=self.session), contextlib.redirect_stderr(stderr):
            self.assertEqual(cli.main(["--start"]), 1)
        self.assertIn("Hyprland", stderr.getvalue())
        self.assertFalse(self.fake.calls)


if __name__ == "__main__":
    unittest.main()

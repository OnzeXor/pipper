from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import tomllib
import unittest
from unittest.mock import patch

from src.config_manager import (ConfigManager, HyprlandController, LAYERS,
    MonitorSettings, PipperError, WayVNCManager, atomic_write, nearest_scale,
    run_command, editor_command)


class ValidationTests(unittest.TestCase):
    def test_native_scale_correction(self):
        settings, notice = MonitorSettings(resolution="2340x1080", scale="3.5").validated()
        self.assertEqual(settings.scale, "3.6")
        self.assertIn("ajustada", notice)
        self.assertEqual(Decimal(2340) / Decimal(settings.scale), 650)
        self.assertEqual(Decimal(1080) / Decimal(settings.scale), 300)

    def test_all_presets_have_valid_scales(self):
        presets = json.loads((Path(__file__).parents[1] / "src/devices.json").read_text())
        self.assertEqual(presets[0]["output"], "S22")
        for preset in presets:
            _, notice = MonitorSettings.from_preset(preset).validated()
            self.assertIsNone(notice, preset["name"])

    def test_valid_precise_scale_is_preserved(self):
        self.assertEqual(nearest_scale(1920, 1080, Decimal("1.875")), Decimal("1.875"))

    def test_reject_injection_and_nonfinite_numbers(self):
        for key, value in [("output", 'S22"; os.execute("x")'), ("output", "--help"),
                           ("workspace", "11;exec"), ("resolution", "0x1080"),
                           ("position", "0x0;exec"), ("scale", "NaN"),
                           ("scale", "Infinity"), ("refresh", "NaN")]:
            with self.subTest(key=key, value=value), self.assertRaises(PipperError):
                replace(MonitorSettings(), **{key: value}).validated()


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.manager = ConfigManager(self.root)
        self.manager.hypr_dir.mkdir()
        self.manager.noctalia_path.parent.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def test_lua_save_preserves_user_content_backup_and_is_idempotent(self):
        path = self.manager.hypr_path
        original = '-- my config\nrequire("monitors")\n'
        path.write_text(original)
        backup = self.manager.save_hypr(MonitorSettings())
        self.assertEqual(backup.read_text(), original)
        first = path.read_text()
        self.assertTrue(first.startswith(original))
        self.assertEqual(first.count("[PIPPER START]"), 1)
        self.assertIsNone(self.manager.save_hypr(MonitorSettings()))
        self.manager.save_hypr(MonitorSettings(position="-1920x0"))
        self.assertEqual(path.read_text().count("[PIPPER START]"), 1)
        self.assertEqual(self.manager.read_hypr(MonitorSettings()).position, "-1920x0")

    def test_literal_includes_are_read_in_order_and_cycles_stop(self):
        self.manager.hypr_path.write_text('hl.monitor({output="S22", mode="1920x1080@60", position="0x0", scale=1})\nrequire("hyprmon")\nhl.workspace_rule({workspace="14", monitor="S22"})\n')
        (self.manager.hypr_dir / "hyprmon.lua").write_text('require("hyprland")\nhl.monitor({output="S22", mode="2340x1080@60", position="3552x1376", scale=3.6})\n')
        settings = self.manager.read_hypr(MonitorSettings())
        self.assertEqual(settings.resolution, "2340x1080")
        self.assertEqual(settings.position, "3552x1376")
        self.assertEqual(settings.workspace, "14")

    def test_legacy_conf_discovery_and_persistence(self):
        path = self.manager.hypr_dir / "hyprland.conf"
        path.write_text('monitor = S22,2340x1080@60,-1920x0,3.6\nworkspace = 12,monitor:S22,default:true\n')
        settings = self.manager.read_hypr(MonitorSettings())
        self.assertEqual(settings.workspace, "12")
        self.assertEqual(settings.scale, "3.6")
        self.manager.save_hypr(settings)
        self.assertIn("# [PIPPER START]", path.read_text())
        self.assertFalse((self.manager.hypr_dir / "hyprland.lua").exists())

    def test_commented_lua_include_is_not_discovered(self):
        self.manager.hypr_path.write_text('-- require("unused")\n')
        (self.manager.hypr_dir / "unused.lua").write_text('hl.monitor({output="S22", position="999x999", scale=1})')
        self.assertEqual(self.manager.read_hypr(MonitorSettings()).position, "3552x1376")

    def test_editor_preferences_survive_reopening(self):
        self.assertEqual(self.manager.read_preferences()["editor"], "auto")
        self.manager.save_preferences("hyprmon", "kitty -e hyprmon")
        reopened = ConfigManager(self.root)
        self.assertEqual(reopened.read_preferences(), {"editor": "hyprmon", "custom_command": "kitty -e hyprmon"})
        self.manager.save_preferences("custom", 'foot -e "/opt/my editor"')
        self.assertEqual(reopened.read_preferences()["editor"], "custom")

    def test_invalid_preferences_report_error_without_overwriting(self):
        path = self.manager.preferences_path
        path.parent.mkdir(parents=True)
        path.write_text("[not-json")
        with self.assertRaises(PipperError):
            self.manager.read_preferences()
        self.assertEqual(path.read_text(), "[not-json")

    def test_malformed_managed_block_never_overwrites_config(self):
        path = self.manager.hypr_path
        original = '-- [PIPPER START]\nmy_config()\n'
        path.write_text(original)
        with self.assertRaises(PipperError):
            self.manager.save_hypr(MonitorSettings())
        self.assertEqual(path.read_text(), original)

    def test_noctalia_aliases_roundtrip_and_comments(self):
        original = '# keep me\n[theme]\nmode = "dark"\n[bar.default.monitor.celular]\nmatch = "S22"\nenabled = false\n[dock.monitor.desktop]\nmatch = "eDP-1"\nenabled = true\n'
        path = self.manager.noctalia_path
        path.write_text(original)
        self.assertTrue(self.manager.read_exclusions("S22")["bar.default"])
        backup = self.manager.save_exclusions("S22", dict.fromkeys(LAYERS, True))
        self.assertEqual(backup.read_text(), original)
        self.assertTrue(all(self.manager.read_exclusions("S22").values()))
        self.manager.save_exclusions("S22", {"bar.default": False})
        content = path.read_text()
        self.assertIn("# keep me", content)
        document = tomllib.loads(content)
        self.assertTrue(document["bar"]["default"]["monitor"]["celular"]["enabled"])
        self.assertTrue(document["dock"]["monitor"]["desktop"]["enabled"])
        self.assertFalse(self.manager.read_exclusions("S22")["bar.default"])
        self.assertTrue(self.manager.read_exclusions("S22")["dock"])

    def test_rename_moves_owned_rules_without_changing_other_monitor(self):
        self.manager.save_exclusions("S22", dict.fromkeys(LAYERS, True))
        self.manager.save_exclusions("PocoM4", dict.fromkeys(LAYERS, True))
        document = tomllib.loads(self.manager.noctalia_path.read_text())
        self.assertEqual(document["dock"]["monitor"]["pipper"]["match"], "PocoM4")
        self.assertFalse(any(self.manager.read_exclusions("S22").values()))

    def test_invalid_toml_is_preserved(self):
        original = '[dock\nfoo = "bar"'
        self.manager.noctalia_path.write_text(original)
        with self.assertRaises(PipperError):
            self.manager.save_exclusions("S22", {"dock": True})
        self.assertEqual(self.manager.noctalia_path.read_text(), original)

    def test_atomic_write_preserves_symlink_and_detects_concurrent_changes(self):
        target, link = self.root / "actual.lua", self.root / "linked.lua"
        target.write_text("original")
        link.symlink_to(target)
        atomic_write(link, "updated", "original")
        self.assertTrue(link.is_symlink())
        self.assertEqual(target.read_text(), "updated")
        with self.assertRaises(PipperError):
            atomic_write(link, "lost update", "original")
        self.assertEqual(target.read_text(), "updated")


class FakeHypr:
    def __init__(self, outputs=None, named=True, fail_configure=False):
        self.outputs = outputs or []
        self.calls = []
        self.named = named
        self.fail_configure = fail_configure

    def __call__(self, args):
        self.calls.append(args)
        if args[1] == "monitors":
            return json.dumps(self.outputs)
        if args[1:3] == ["output", "create"]:
            self.outputs.append({"name": args[-1] if self.named else "HEADLESS-1", "x": 20, "y": 30, "scale": 2})
        elif args[1:3] == ["output", "remove"]:
            self.outputs = [m for m in self.outputs if m["name"] != args[-1]]
        elif args[1] == "eval" and self.fail_configure:
            raise PipperError("Lua failure")
        return "ok"


class ControllerTests(unittest.TestCase):
    def test_explicit_hyprmon_launches_in_kitty_and_tracks_process(self):
        fake = FakeHypr()
        controller = HyprlandController(fake, lambda _: None)
        with patch("src.config_manager.shutil.which", return_value="/usr/bin/program"), \
             patch("src.config_manager.subprocess.Popen") as popen:
            process, created = controller.editor(MonitorSettings(), "hyprmon")
            popen.assert_called_once_with(["kitty", "-e", "hyprmon"])
            self.assertIs(process, popen.return_value)
            self.assertTrue(created)
            self.assertIn("S22", controller.temporary_outputs)

    def test_missing_editor_is_reported_before_creating_output(self):
        fake = FakeHypr()
        controller = HyprlandController(fake, lambda _: None)
        with patch("src.config_manager.shutil.which", return_value=None), self.assertRaises(PipperError):
            controller.editor(MonitorSettings(), "hyprmon")
        self.assertEqual(fake.calls, [])

    def test_custom_editor_quoted_arguments_and_no_shell(self):
        with patch("src.config_manager.shutil.which", return_value="/usr/bin/foot"):
            self.assertEqual(editor_command("custom", 'foot -e "/opt/my editor" --profile "my phone"'),
                             ["foot", "-e", "/opt/my editor", "--profile", "my phone"])
            # Shell operators remain ordinary arguments and are never evaluated.
            self.assertEqual(editor_command("custom", "editor ; touch /tmp/example"),
                             ["editor", ";", "touch", "/tmp/example"])
            with self.assertRaises(PipperError):
                editor_command("custom", 'kitty "unterminated')
            with self.assertRaises(PipperError):
                editor_command("custom", "")

    def test_auto_editor_falls_back_when_kitty_is_missing(self):
        available = {"hyprmon", "nwg-displays"}
        with patch("src.config_manager.shutil.which", side_effect=lambda p: f"/usr/bin/{p}" if p in available else None):
            self.assertEqual(editor_command(), ["nwg-displays"])

    def test_editor_launch_failure_only_removes_new_output(self):
        for existing in (False, True):
            with self.subTest(existing=existing):
                fake = FakeHypr([{"name": "S22"}] if existing else [])
                controller = HyprlandController(fake, lambda _: None)
                with patch("src.config_manager.shutil.which", return_value="/usr/bin/editor"), \
                     patch("src.config_manager.subprocess.Popen", side_effect=OSError("cannot launch")), \
                     self.assertRaises(PipperError):
                    controller.editor(MonitorSettings(), "custom", "editor --layout phone")
                self.assertEqual(bool(fake.outputs), existing)

    def test_reuses_existing_output(self):
        fake = FakeHypr([{"name": "S22"}])
        controller = HyprlandController(fake, lambda _: None)
        self.assertFalse(controller.ensure_output(MonitorSettings()))
        self.assertFalse(any(call[1] == "output" for call in fake.calls))

    def test_creates_configures_syncs_and_removes_temporary_output(self):
        fake = FakeHypr()
        controller = HyprlandController(fake, lambda _: None)
        self.assertTrue(controller.ensure_output(MonitorSettings(), temporary=True))
        self.assertIn("S22", controller.temporary_outputs)
        settings = controller.sync(MonitorSettings())
        self.assertEqual(settings.position, "20x30")
        controller.activate_workspace(settings)
        self.assertIn("hl.dsp.workspace.move", fake.calls[-1][-1])
        controller.remove_output("S22")
        self.assertEqual(fake.outputs, [])
        self.assertEqual(controller.temporary_outputs, set())

    def test_unexpected_headless_name_is_cleaned_up(self):
        fake = FakeHypr(named=False)
        controller = HyprlandController(fake, lambda _: None)
        with self.assertRaisesRegex(PipperError, "nome S22"):
            controller.ensure_output(MonitorSettings())
        self.assertEqual(fake.outputs, [])

    def test_configuration_failure_rolls_back_new_output(self):
        fake = FakeHypr(fail_configure=True)
        controller = HyprlandController(fake, lambda _: None)
        with self.assertRaises(PipperError):
            controller.ensure_output(MonitorSettings())
        self.assertEqual(fake.outputs, [])

    def test_monitor_json_updates_geometry_preserving_target_workspace(self):
        fake = FakeHypr([{"name": "S22", "width": 2340, "height": 1080, "refreshRate": 60.001,
                         "x": -650, "y": 40, "scale": 3.6, "activeWorkspace": {"id": 12}}])
        controller = HyprlandController(fake)
        settings = controller.discover(MonitorSettings())
        self.assertEqual(settings.resolution, "2340x1080")
        self.assertEqual(settings.workspace, "11")
        self.assertEqual(settings.position, "-650x40")
        self.assertEqual(controller.discover(MonitorSettings(workspace="17")).workspace, "17")

    def test_selected_workspace_is_bound_focused_and_moved_to_phone(self):
        fake = FakeHypr([{"name": "S22"}])
        controller = HyprlandController(fake)
        settings = MonitorSettings(workspace="17")
        controller.configure(settings)
        controller.activate_workspace(settings)
        rules, focus, move = [call[-1] for call in fake.calls if call[1] == "eval"][1:]
        self.assertIn('workspace = "17"', rules)
        self.assertIn('monitor = "S22"', rules)
        self.assertIn('workspace = "17"', focus)
        self.assertIn('workspace = "17"', move)
        self.assertIn('monitor = "S22"', move)

    def test_hyprctl_lua_error_with_zero_exit_status_is_reported(self):
        result = subprocess.CompletedProcess([], 0, 'attempt to call a nil value', '')
        with patch("src.config_manager.subprocess.run", return_value=result), self.assertRaises(PipperError):
            run_command(["hyprctl", "eval", "hl.wrong()"])

    def test_wayvnc_early_exit_surfaces_log(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = WayVNCManager(Path(directory))
            with patch("src.config_manager.shutil.which", return_value="/usr/bin/wayvnc"), \
                 patch.object(manager, "stop"), \
                 patch("src.config_manager.time.sleep"), \
                 patch("src.config_manager.subprocess.Popen") as popen:
                popen.return_value.poll.return_value = 1
                with self.assertRaisesRegex(PipperError, "wayvnc não iniciou"):
                    manager.start(MonitorSettings())
                self.assertIsNone(manager.process)

    def test_wayvnc_detaches_and_records_unsaved_device(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = WayVNCManager(Path(directory))
            settings = MonitorSettings(output="CustomPhone", position="200x40")
            with patch("src.config_manager.shutil.which", return_value="/usr/bin/wayvnc"), \
                 patch.object(manager, "stop"), patch("src.config_manager.time.sleep"), \
                 patch("src.config_manager.subprocess.Popen") as popen:
                popen.return_value.poll.return_value = None
                manager.start(settings)
                kwargs = popen.call_args.kwargs
                self.assertTrue(kwargs["start_new_session"])
                self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
                reopened = WayVNCManager(Path(directory))
                with patch.object(reopened, "is_running", return_value=True):
                    self.assertEqual(reopened.running_settings(), settings)
                with patch.object(reopened, "is_running", return_value=False):
                    self.assertIsNone(reopened.running_settings())
                reopened._forget_session("OtherPhone")
                self.assertTrue(reopened.session_path.exists())
                reopened._forget_session("CustomPhone")
                self.assertFalse(reopened.session_path.exists())

    def test_detached_process_survives_parent_exit_and_can_be_stopped(self):
        # A sleeping Python child stands in for VNC: no socket, monitor or network.
        # Its argv[0] is 'wayvnc' so recovery exercises the real /proc scan.
        with tempfile.TemporaryDirectory() as directory:
            output = "PipperTest-" + Path(directory).name
            code = textwrap.dedent('''
                import subprocess, sys
                from pathlib import Path
                from unittest.mock import patch
                from src.config_manager import MonitorSettings, WayVNCManager
                original_popen = subprocess.Popen
                def sleeper(args, **kwargs):
                    return original_popen(["wayvnc", "-c", "import time; time.sleep(30)",
                                           args[1]], executable=sys.executable, **kwargs)
                manager = WayVNCManager(Path(sys.argv[1]))
                with patch("src.config_manager.shutil.which", return_value=sys.executable), \
                     patch("src.config_manager.subprocess.Popen", side_effect=sleeper):
                    manager.start(MonitorSettings(output=sys.argv[2]))
            ''')
            reopened = WayVNCManager(Path(directory))
            try:
                subprocess.run([sys.executable, "-c", code, directory, output],
                               cwd=Path(__file__).parents[1], check=True, timeout=10,
                               capture_output=True, text=True)
                self.assertTrue(reopened.is_running(output))
                self.assertEqual(reopened.running_settings().output, output)
                processes = reopened.matching_processes(output)
                self.assertTrue(processes)
                import os
                self.assertEqual(os.getsid(processes[0][0]), processes[0][0])
            finally:
                reopened.stop(output)
            self.assertFalse(reopened.is_running(output))
            self.assertFalse(reopened.session_path.exists())


if __name__ == "__main__":
    unittest.main()

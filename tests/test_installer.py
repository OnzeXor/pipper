"""Exercise the installer through a pipe and PTY; never use real sudo/pacman."""
import errno
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import pty
import select
import subprocess
import sys
import tarfile
import tempfile
import termios
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMMIT = '53ddff964314261cc6cee973b21da74abc52b258'
SOURCE_HASH = '173772542e2812871eb2c95125c4a5f46b0155edd9da773d9cfb067d68ecf83b'


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='pipper-installer-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.log = self.root / 'calls.jsonl'
        self.archive = self.root / 'fixture.tar.gz'
        fixture = b'''import os, pathlib, sys
assert os.environ.get('BUILD_FAIL') != '1', 'simulated build failure'
output = pathlib.Path(sys.argv[sys.argv.index('--output') + 1])
output.mkdir(parents=True)
(output / 'pipper-0.1.0-1-any.pkg.tar.zst').write_text('simulated package')
'''
        files = {'scripts/build_arch.py': fixture, 'src/cli.py': b'# fixture',
                 'pipper': b'print("Pipper 0.1.0")', 'LICENSE': b'MIT',
                 'data/pipper.desktop': (ROOT / 'data/pipper.desktop').read_bytes(),
                 'data/icons/pipper.png': b'fixture icon'}
        with tarfile.open(self.archive, 'w:gz') as tar:
            for name, data in files.items():
                info = tarfile.TarInfo(f'pipper-{COMMIT}/{name}')
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        self.os_release = self.root / 'os-release'
        self.os_release.write_text('ID=arch\nPRETTY_NAME="Test Arch"\n')
        script = (ROOT / 'scripts/install.sh').read_text()
        # Substitute only the expected source digest, keeping the actual
        # checksum check and archive extraction in the installer under test.
        script = script.replace(SOURCE_HASH, hashlib.sha256(self.archive.read_bytes()).hexdigest())
        self.installer = self.root / 'install.sh'
        script = script.replace('/etc/os-release', str(self.os_release))
        script = script.replace('/run/ostree-booted', str(self.root / 'ostree-booted'))
        script = script.replace('local python_executable=/usr/bin/python3',
                                'local python_executable=' + str(self.bin / 'python3'))
        self.installer.write_text(script)
        self.env = {**os.environ, 'PATH': str(self.bin) + os.pathsep + os.environ['PATH'],
                    'CALL_LOG': str(self.log), 'FIXTURE': str(self.archive),
                    'TMPDIR': str(self.root), 'MOCK_UID': '1000',
                    'HOME': str(self.root / 'home'), 'XDG_DATA_HOME': str(self.root / 'data'),
                    'XDG_CONFIG_HOME': str(self.root / 'config')}
        self.mock('id', "import os\nprint(os.environ['MOCK_UID'])")
        self.mock('curl', '''import os, shutil, sys
if os.environ.get('CURL_FAIL') == '1': sys.exit(22)
output = sys.argv[sys.argv.index('--output') + 1]
shutil.copyfile(os.environ['FIXTURE'], output)
''')
        self.mock('sudo', '''import json, os, subprocess, sys
with open(os.environ['CALL_LOG'], 'a') as log:
    log.write(json.dumps({'argv': sys.argv[1:], 'tty': os.isatty(0)}) + '\\n')
if sys.argv[1:] == ['-v']: sys.exit(0)
assert sys.argv[1] in {'pacman', 'apt-get', 'dnf', 'zypper', 'apk', 'xbps-install'}
sys.exit(subprocess.call(sys.argv[1:]))
''')
        self.mock('pacman', '''import os, pathlib, sys
if sys.argv[1] == '-Syu':
    sys.exit(1 if os.environ.get('PACMAN_FAIL') == '1' else 0)
assert sys.argv[1:3] == ['-U', '--']
if os.environ.get('PACKAGE_FAIL') == '1': sys.exit(1)
assert pathlib.Path(sys.argv[3]).is_file()
''')

        self.mock('python3', '''import os, subprocess, sys
if len(sys.argv) > 1 and sys.argv[1] == '-c':
    sys.exit(1 if os.environ.get('RUNTIME_FAIL') == '1' else 0)
sys.exit(subprocess.call([sys.executable, *sys.argv[1:]]))
''')
        for name in ['apt-get', 'dnf', 'zypper', 'apk', 'xbps-install']:
            self.mock(name, '''import os, sys
sys.exit(1 if os.environ.get('PACMAN_FAIL') == '1' else 0)
''')
        self.mock('wayvnc', 'pass')

    def set_distro(self, name, like=''):
        self.os_release.write_text(f'ID={name}\nID_LIKE="{like}"\nPRETTY_NAME="Test {name}"\n')

    def mock(self, name, code):
        path = self.bin / name
        path.write_text(f'#!{sys.executable}\n' + code + '\n')
        path.chmod(0o755)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def execute(self, *args, terminal=False):
        if not terminal:
            result = subprocess.run(['bash', str(self.installer), *args], env=self.env,
                                    capture_output=True, text=True, start_new_session=True)
            return result.returncode, result.stdout + result.stderr
        master, slave = pty.openpty()

        def attach():
            os.setsid()
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)

        # The inner bash consumes a pipe, just as with curl URL | bash.
        process = subprocess.Popen(['bash', '-c', 'cat "$1" | bash -s -- "${@:2}"', '--', str(self.installer), *args],
                                   env=self.env, stdin=slave, stdout=slave, stderr=slave, preexec_fn=attach)
        os.close(slave)
        output = bytearray()
        deadline = time.monotonic() + 15
        try:
            while time.monotonic() < deadline:
                if select.select([master], [], [], 0.1)[0]:
                    try:
                        data = os.read(master, 65536)
                    except OSError as error:
                        if error.errno == errno.EIO:
                            break
                        raise
                    if not data:
                        break
                    output.extend(data)
                elif process.poll() is not None:
                    break
            if process.poll() is None:
                process.wait(timeout=2)
            return process.returncode, output.decode(errors='replace')
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            os.close(master)

    def assert_clean(self):
        self.assertEqual(list(self.root.glob('pipper-install.*')), [])

    def test_help_and_preview_do_not_install_or_download(self):
        for flag in ('--help', '--dry-run'):
            code, text = self.execute(flag)
            self.assertEqual(code, 0, text)
        self.assertIn('pacman -Syu', text)
        self.assertIn('python-qrcode', text)
        self.assertEqual(self.calls(), [])
        self.assert_clean()

    def test_unknown_option_is_rejected(self):
        self.assertEqual(self.execute('--nonsense')[0], 2)
        self.assertEqual(self.calls(), [])

    def test_root_is_rejected_before_any_changes(self):
        self.env['MOCK_UID'] = '0'
        code, text = self.execute()
        self.assertNotEqual(code, 0)
        self.assertIn('sem sudo', text)
        self.assertEqual(self.calls(), [])

    def test_noninteractive_session_is_rejected(self):
        code, text = self.execute()
        self.assertNotEqual(code, 0)
        self.assertIn('terminal interativo', text)
        self.assertEqual(self.calls(), [])

    def test_pipe_preserves_terminal_for_sudo_and_pacman(self):
        code, text = self.execute(terminal=True)
        self.assertEqual(code, 0, text)
        calls = self.calls()
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(call['tty'] for call in calls))
        self.assertEqual(calls[0]['argv'], ['-v'])
        self.assertEqual(calls[1]['argv'][:4], ['pacman', '-Syu', '--needed', '--'])
        self.assertIn('hyprland>=0.55', calls[1]['argv'])
        self.assertEqual(calls[2]['argv'][:3], ['pacman', '-U', '--'])
        self.assertIn('Pipper instalado', text)
        self.assert_clean()

    def test_bad_checksum_stops_before_sudo(self):
        self.archive.write_bytes(b'corrupted download')
        code, text = self.execute(terminal=True)
        self.assertNotEqual(code, 0)
        self.assertIn('SHA-256 falhou', text)
        self.assertEqual(self.calls(), [])
        self.assert_clean()

    def test_failed_download_stops_before_sudo(self):
        self.env['CURL_FAIL'] = '1'
        code, _ = self.execute(terminal=True)
        self.assertNotEqual(code, 0)
        self.assertEqual(self.calls(), [])
        self.assert_clean()

    def test_failed_dependency_install_does_not_install_pipper(self):
        self.env['PACMAN_FAIL'] = '1'
        code, text = self.execute(terminal=True)
        self.assertNotEqual(code, 0)
        self.assertEqual(len(self.calls()), 2)
        self.assertNotIn('Pipper instalado', text)
        self.assert_clean()

    def test_failed_build_does_not_install_pipper(self):
        self.env['BUILD_FAIL'] = '1'
        code, text = self.execute(terminal=True)
        self.assertNotEqual(code, 0)
        self.assertEqual(len(self.calls()), 2)
        self.assertNotIn('Pipper instalado', text)
        self.assert_clean()

    def test_failed_package_install_does_not_report_success(self):
        self.env['PACKAGE_FAIL'] = '1'
        code, text = self.execute(terminal=True)
        self.assertNotEqual(code, 0)
        self.assertEqual(len(self.calls()), 3)
        self.assertNotIn('Pipper instalado', text)
        self.assert_clean()

    def test_family_detection_and_preview(self):
        cases = [('ubuntu', 'debian', 'apt-get'), ('linuxmint', 'ubuntu debian', 'apt-get'),
                 ('fedora', '', 'dnf'), ('opensuse-tumbleweed', 'suse', 'zypper'),
                 ('alpine', '', 'apk'), ('void', '', 'xbps-install'),
                 ('cachyos', 'arch', 'pacman')]
        for name, like, manager in cases:
            with self.subTest(distro=name):
                self.set_distro(name, like)
                code, text = self.execute('--dry-run')
                self.assertEqual(code, 0, text)
                self.assertIn(manager, text)
                self.assertEqual(self.calls(), [])

    def test_portable_install_for_each_package_manager(self):
        for name, manager, action in [('debian', 'apt-get', 'install'), ('fedora', 'dnf', 'install'),
                                      ('opensuse-tumbleweed', 'zypper', 'install'),
                                      ('alpine', 'apk', 'add'), ('void', 'xbps-install', '--')]:
            with self.subTest(distro=name):
                self.set_distro(name)
                self.log.unlink(missing_ok=True)
                code, text = self.execute(terminal=True)
                self.assertEqual(code, 0, text)
                calls = self.calls()
                self.assertTrue(all(c['tty'] for c in calls))
                self.assertTrue(any(c['argv'][:2] == [manager, action] for c in calls), calls)
                self.assertFalse(any('pacman' in c['argv'] for c in calls))
                launcher = self.root / 'home/.local/bin/pipper'
                result = subprocess.run([str(launcher), '--version'], env=self.env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('Pipper 0.1.0', result.stdout)
                desktop = (self.root / 'data/applications/pipper.desktop').read_text()
                self.assertIn(f'Exec="{launcher}" --toggle', desktop)
                self.assert_clean()

    def test_user_uninstall_preserves_preferences_and_vicinae_backups(self):
        self.set_distro('ubuntu', 'debian')
        backup = self.root / 'data/pipper/vicinae-backups/keep.txt'
        config = self.root / 'config/pipper/preferences.json'
        for path in [backup, config]:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('keep')
        code, text = self.execute(terminal=True)
        self.assertEqual(code, 0, text)
        launcher = self.root / 'home/.local/bin/pipper'
        result = subprocess.run([str(launcher), '--uninstall'], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(launcher.exists())
        self.assertFalse((self.root / 'data/pipper/app').exists())
        self.assertFalse((self.root / 'data/applications/pipper.desktop').exists())
        self.assertEqual(backup.read_text(), 'keep')
        self.assertEqual(config.read_text(), 'keep')

    def test_old_runtime_does_not_publish_user_install(self):
        self.set_distro('debian')
        self.env['RUNTIME_FAIL'] = '1'
        code, text = self.execute(terminal=True)
        self.assertNotEqual(code, 0)
        self.assertIn('Dependências incompletas', text)
        self.assertFalse((self.root / 'home/.local/bin/pipper').exists())
        self.assert_clean()

    def test_unknown_and_immutable_systems_never_run_package_managers(self):
        for name, like in [('nixos', ''), ('aeon', 'suse'), ('opensuse-microos', 'suse'),
                           ('steamos', 'arch'), ('customlinux', '')]:
            with self.subTest(distro=name):
                self.set_distro(name, like)
                self.env['RUNTIME_FAIL'] = '1'
                code, text = self.execute()
                self.assertNotEqual(code, 0)
                self.assertIn('Dependências incompletas', text)
                self.assertEqual(self.calls(), [])
                self.assert_clean()

    def test_ostree_detection_prevents_dnf_changes(self):
        self.set_distro('fedora')
        (self.root / 'ostree-booted').touch()
        self.env['RUNTIME_FAIL'] = '1'
        code, text = self.execute()
        self.assertNotEqual(code, 0)
        self.assertIn('imutável', text)
        self.assertEqual(self.calls(), [])

    def test_generic_install_when_runtime_is_already_available(self):
        self.set_distro('customlinux')
        code, text = self.execute()
        self.assertEqual(code, 0, text)
        self.assertEqual(self.calls(), [])
        self.assertTrue((self.root / 'home/.local/bin/pipper').is_file())

    def test_user_paths_with_spaces(self):
        self.set_distro('debian')
        self.env['HOME'] = str(self.root / 'home with spaces')
        self.env['XDG_DATA_HOME'] = str(self.root / 'data with spaces')
        code, text = self.execute(terminal=True)
        self.assertEqual(code, 0, text)
        launcher = Path(self.env['HOME']) / '.local/bin/pipper'
        result = subprocess.run([str(launcher), '--version'], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_portable_dependency_failure_keeps_existing_installation(self):
        self.set_distro('debian')
        code, text = self.execute(terminal=True)
        self.assertEqual(code, 0, text)
        current = self.root / 'data/pipper/app/current'
        previous = current.resolve()
        self.env['PACMAN_FAIL'] = '1'
        code, text = self.execute(terminal=True)
        self.assertNotEqual(code, 0)
        self.assertEqual(current.resolve(), previous)
        self.assertNotIn('Pipper instalado', text)

    def test_skip_dependencies_installs_for_user_without_sudo(self):
        code, text = self.execute('--skip-dependencies')
        self.assertEqual(code, 0, text)
        self.assertEqual(self.calls(), [])
        self.assertTrue((self.root / 'home/.local/bin/pipper').exists())

    def test_failed_desktop_write_restores_previous_launcher(self):
        self.set_distro('debian')
        code, text = self.execute(terminal=True)
        self.assertEqual(code, 0, text)
        launcher = self.root / 'home/.local/bin/pipper'
        previous = launcher.read_text() + '# original installation\n'
        launcher.write_text(previous)
        current = self.root / 'data/pipper/app/current'
        old_release = current.resolve()
        desktop = self.root / 'data/applications/pipper.desktop'
        desktop.unlink()
        desktop.mkdir()
        code, text = self.execute(terminal=True)
        self.assertNotEqual(code, 0)
        self.assertEqual(launcher.read_text(), previous)
        self.assertEqual(current.resolve(), old_release)
        self.assertTrue(desktop.is_dir())
        self.assert_clean()


if __name__ == '__main__':
    unittest.main()

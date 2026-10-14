#!/usr/bin/env python3
"""Validate the built wheel in an isolated prefix without changing the system."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()
    wheel = args.wheel.resolve()
    with tempfile.TemporaryDirectory(prefix="pipper-wheel-") as directory:
        stage = Path(directory)
        subprocess.run([sys.executable, "-m", "installer", "--destdir", str(stage), "--prefix", "/usr", str(wheel)], check=True)
        site = next((stage / "usr/lib").glob("python*/site-packages"))
        env = {**os.environ, "PYTHONPATH": str(site), "PYTHONNOUSERSITE": "1"}
        env["XDG_CONFIG_HOME"] = str(stage / "config")
        env["XDG_STATE_HOME"] = str(stage / "state")
        env["NOCTALIA_CONFIG_HOME"] = str(stage / "config")
        code = '''
import json, sys
from pathlib import Path
from pipper_app import __version__
from pipper_app.paths import checkout_root, data_directory, icon_path, command_argv
from pipper_app import integrations
from pipper_app.integrations import Environment
import pipper_app
import pipper_app.main
root = Path(sys.argv[1])
assert checkout_root() is None
assert str(pipper_app.__file__).startswith(str(root))
assert data_directory() == root / 'usr/share/pipper'
assert icon_path().is_file()
assert command_argv()[1:] == ['-m', 'pipper_app']
assert (Path(pipper_app.__file__).parent / 'style.css').is_file()
assert len(json.loads((Path(pipper_app.__file__).parent / 'devices.json').read_text())) >= 29
scripts = integrations.install_vicinae_scripts(Environment('Hyprland', True, True, False, True), data_home=root / 'test-data')
assert len(scripts) == 4
for script in scripts:
    text = script.read_text()
    assert "'-m', 'pipper_app'" in text
    assert str(root / 'usr/share/pipper/icons/pipper.png') in text
print('Installed package:', __version__, '— CLI, resources and Vicinae scripts OK')
'''
        subprocess.run([sys.executable, "-c", code, str(stage)], cwd=stage, env=env, check=True)
        subprocess.run([str(stage / "usr/bin/pipper"), "--version"], cwd=stage, env=env, check=True)
        subprocess.run([str(stage / "usr/bin/pipper"), "--help"], cwd=stage, env=env, check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["desktop-file-validate", str(stage / "usr/share/applications/pipper.desktop")], check=True)
    print("Instalação temporária verificada; sistema não alterado.")


if __name__ == "__main__":
    main()

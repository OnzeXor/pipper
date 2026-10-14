"""Session-aware integration discovery and native desktop actions."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from .config_manager import PipperError, atomic_write, run_command
from .paths import command_argv, icon_path


@dataclass(frozen=True)
class Environment:
    desktop: str = "Desconhecido"
    wayland: bool = False
    hyprland: bool = False
    noctalia: bool = False
    vicinae: bool = False
    display_settings: tuple[str, ...] = ()

    def require_hyprland(self):
        if not self.hyprland:
            raise PipperError(f"O controle da tela virtual requer uma sessão Hyprland ativa. Ambiente detectado: {self.desktop}.")

    def require_noctalia(self):
        if not self.noctalia:
            raise PipperError("Esta opção requer Noctalia v5 ativo na sessão atual.")

    def require_vicinae(self):
        if not self.vicinae:
            raise PipperError("Esta opção requer Vicinae ativo na sessão atual.")


def running_in_session(program: str, env) -> bool:
    display_key = "WAYLAND_DISPLAY" if env.get("WAYLAND_DISPLAY") and env.get("XDG_SESSION_TYPE") != "x11" else "DISPLAY"
    if not env.get(display_key):
        return False
    process_names = {program, "vicinae-server"} if program == "vicinae" else {program}
    for path in Path("/proc").glob("[0-9]*"):
        try:
            if path.stat().st_uid != os.getuid():
                continue
            if (path / "comm").read_text().strip() not in process_names:
                executable = (path / "cmdline").read_bytes().split(b"\0", 1)[0].decode()
                if Path(executable).name not in process_names:
                    continue
            process_env = dict(item.split("=", 1) for item in
                               (path / "environ").read_bytes().decode().split("\0") if "=" in item)
            keys = [key for key in (display_key, "XDG_RUNTIME_DIR") if env.get(key)]
            if keys and all(process_env.get(key) == env[key] for key in keys):
                return True
        except (OSError, ValueError, UnicodeError):
            continue
    return False


def detect_environment(environ=None, runner=run_command, which=shutil.which, process_check=running_in_session) -> Environment:
    env = os.environ if environ is None else environ
    names = re.split(r"[:;\s]+", env.get("XDG_CURRENT_DESKTOP", "").lower())
    session_type = env.get("XDG_SESSION_TYPE", "").lower()
    wayland = session_type == "wayland" or (session_type != "x11" and bool(env.get("WAYLAND_DISPLAY")))
    if "gnome" in names:
        desktop = "GNOME"
    elif "kde" in names or "plasma" in names:
        desktop = "KDE Plasma"
    elif "sway" in names or env.get("SWAYSOCK"):
        desktop = "Sway"
    elif "niri" in names or env.get("NIRI_SOCKET"):
        desktop = "Niri"
    elif "hyprland" in names:
        desktop = "Hyprland"
    elif names and names[0]:
        desktop = env.get("XDG_CURRENT_DESKTOP", "Desconhecido")
    else:
        desktop = "Desconhecido"
    hyprland = False
    # A leftover socket variable or an installed binary alone is insufficient.
    candidate = wayland and bool(env.get("HYPRLAND_INSTANCE_SIGNATURE")) and desktop in {"Hyprland", "Desconhecido"}
    if candidate and which("hyprctl"):
        try:
            monitors = json.loads(runner(["hyprctl", "monitors", "all", "-j"], timeout=3))
            hyprland = isinstance(monitors, list) and all(isinstance(m, dict) for m in monitors)
            if hyprland:
                desktop = "Hyprland"
        except (PipperError, ValueError, OSError):
            pass
    noctalia = False
    if wayland and which("noctalia") and process_check("noctalia", env):
        try:
            version = runner(["noctalia", "--version"], timeout=2)
            major = re.search(r"\bv?(\d+)\.\d+", version)
            if major and int(major[1]) >= 5:
                status = json.loads(runner(["noctalia", "msg", "status"], timeout=2))
                noctalia = isinstance(status, dict) and not status.get("error")
        except (PipperError, ValueError, OSError):
            pass
    vicinae = False
    if which("vicinae") and process_check("vicinae", env):
        try:
            runner(["vicinae", "ping"], timeout=2)
            vicinae = True
        except (PipperError, OSError):
            pass
    settings = ()
    if desktop == "GNOME" and which("gnome-control-center"):
        settings = ("gnome-control-center", "display")
    elif desktop == "KDE Plasma" and which("systemsettings"):
        settings = ("systemsettings", "kcm_kscreen")
    return Environment(desktop, wayland, hyprland, noctalia, vicinae, settings)


NOCTALIA_ACTIONS = {
    "settings": "settings-open", "reload": "config-reload",
    "dnd": "notification-dnd-toggle",
}


def noctalia_action(environment: Environment, action: str, runner=run_command):
    environment.require_noctalia()
    if action not in NOCTALIA_ACTIONS:
        raise PipperError("Ação do Noctalia desconhecida.")
    return runner(["noctalia", "msg", NOCTALIA_ACTIONS[action]], timeout=5)


def open_display_settings(environment: Environment):
    if not environment.display_settings:
        raise PipperError("Configurações nativas de tela não estão disponíveis neste ambiente.")
    return subprocess.Popen(list(environment.display_settings), stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def install_vicinae_scripts(environment: Environment, launcher: Path | None = None, data_home: Path | None = None) -> list[Path]:
    environment.require_vicinae()
    environment.require_hyprland()
    root = data_home or Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    directory = root / "vicinae/scripts"
    # Vicinae indexes backup files too if they retain script metadata. Keep
    # backups outside every directory scanned by the script provider.
    backup_dir = root / "pipper/vicinae-backups"
    for legacy in directory.glob("pipper-*.py.pipper-*.bak"):
        backup_dir.mkdir(parents=True, exist_ok=True)
        target = backup_dir / legacy.name
        if target.exists():
            target = target.with_name(f"{target.stem}-{time.time_ns()}.bak")
        shutil.move(str(legacy), target)
    actions = {"toggle": ("Pipper — Ligar ou desligar", "--toggle", "compact"),
               "focus": ("Pipper — Workspace do celular", "--focus", "compact"),
               "status": ("Pipper — Conexão e status", "--status", "fullOutput"),
               "open": ("Pipper — Abrir aplicativo", None, "compact")}
    paths = []
    base_argv = [sys.executable, str(launcher.resolve())] if launcher else command_argv()
    icon = launcher.resolve().parent / "data/icons/hicolor/256x256/apps/pipper.png" if launcher else icon_path()
    for name, (title, flag, mode) in actions.items():
        path = directory / f"pipper-{name}.py"
        argv = base_argv + ([flag] if flag else [])
        body = (f"os.execv({sys.executable!r}, {argv!r})" if flag else
                f"subprocess.Popen({argv!r}, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, "
                'stderr=subprocess.DEVNULL, start_new_session=True)\nprint("Abrindo Pipper.")')
        content = (f"#!/usr/bin/env python3\n# @vicinae.schemaVersion 1\n# @vicinae.title {title}\n"
                   f"# @vicinae.mode {mode}\n# @vicinae.author Pipper\n"
                   f"# @vicinae.icon {icon}\n"
                   '# @vicinae.keywords ["pipper", "monitor", "celular"]\n'
                   "import os, subprocess\n" + body + "\n")
        original = path.read_text() if path.exists() else None
        atomic_write(path, content, original, backup_dir=backup_dir)
        path.chmod(0o700)
        paths.append(path)
    return paths


def refresh_vicinae_scripts(environment: Environment, runner=run_command, pause=time.sleep) -> list[dict]:
    """Ask the running server to rescan and verify all four commands are indexed."""
    environment.require_vicinae()
    expected = {"Pipper — Ligar ou desligar", "Pipper — Workspace do celular",
                "Pipper — Conexão e status", "Pipper — Abrir aplicativo"}
    runner(["vicinae", "cmd", "launch", "core:reload-scripts"], timeout=6)
    for attempt in range(5):
        try:
            commands = json.loads(runner(["vicinae", "cmd", "ls", "--json"], timeout=6))
        except ValueError as exc:
            raise PipperError("Scripts instalados, mas o Vicinae retornou um índice inválido.") from exc
        if not isinstance(commands, list):
            raise PipperError("Scripts instalados, mas o formato do índice do Vicinae é desconhecido.")
        indexed = [command for command in commands if isinstance(command, dict) and command.get("name") in expected
                   and ".pipper-" not in str(command.get("id", ""))]
        if {command["name"] for command in indexed} == expected:
            return indexed
        if attempt < 4:
            pause(.2)
    raise PipperError("Os arquivos foram instalados, mas os quatro comandos ainda não estão no índice. Confira as pastas de scripts nas configurações do Vicinae e use Reload Script Directories.")

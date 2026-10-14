"""Control Pipper from launchers and compositor shortcuts without loading GTK."""
import argparse
import json
import sys

from .config_manager import ConfigManager, HyprlandController, PipperError, WayVNCManager, local_addresses
from .integrations import detect_environment
from .session import Session
from . import __version__


def main(argv=None):
    parser = argparse.ArgumentParser(prog="pipper", description="Celular como monitor sem fio no Hyprland.")
    parser.add_argument("--version", action="version", version=f"Pipper {__version__}")
    actions = parser.add_mutually_exclusive_group()
    for flag, description in {"start": "Ligar o último perfil", "stop": "Desligar a sessão",
                              "toggle": "Alternar ligado/desligado", "focus": "Focar o workspace do celular",
                              "status": "Mostrar status e endereço de conexão"}.items():
        actions.add_argument("--" + flag, action="store_true", help=description)
    parser.add_argument("--json", action="store_true", help="Status em JSON (com --status)")
    args = parser.parse_args(argv)
    if args.json and not args.status:
        parser.error("--json requer --status")
    if not any(getattr(args, action) for action in ("start", "stop", "toggle", "focus", "status")):
        from .main import main as gui_main
        return gui_main()
    try:
        environment = detect_environment()
        session = Session(ConfigManager(), HyprlandController(), WayVNCManager())
        if args.status:
            settings = session.settings()
            addresses = local_addresses()
            status = {"desktop": environment.desktop, "hyprland_active": environment.hyprland,
                      "running": session.vnc.is_running(settings.output), "output": settings.output,
                      "workspace": settings.workspace, "addresses": [f"vnc://{ip}:5900" for ip in addresses]}
            if args.json:
                print(json.dumps(status, ensure_ascii=False))
            else:
                print(f"Pipper: {'ligado' if status['running'] else 'desligado'}\nAmbiente: {environment.desktop}\n"
                      f"Output: {settings.output}\nWorkspace do celular: {settings.workspace}\n" +
                      "\n".join(status["addresses"]))
        elif args.toggle:
            print(session.toggle(environment))
        elif args.focus:
            print(session.focus(environment))
        elif args.start:
            settings = session.settings()
            session.start(settings, environment)
            print(f"{settings.output} ligado no workspace {settings.workspace}.")
        elif args.stop:
            session.stop(session.settings().output, environment)
            print("Pipper desligado.")
        return 0
    except (PipperError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

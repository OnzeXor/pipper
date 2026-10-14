"""Shared UI/CLI lifecycle with a lock against overlapping toggle operations."""
from contextlib import contextmanager
import fcntl
import time

from .config_manager import ConfigManager, HyprlandController, MonitorSettings, PipperError, WayVNCManager
from .integrations import Environment


class Session:
    def __init__(self, manager: ConfigManager, hypr: HyprlandController, vnc: WayVNCManager):
        self.manager, self.hypr, self.vnc = manager, hypr, vnc

    @contextmanager
    def lock(self):
        self.vnc.state_dir.mkdir(parents=True, exist_ok=True)
        path = self.vnc.state_dir / "control.lock"
        with path.open("a") as stream:
            path.chmod(0o600)
            deadline = time.monotonic() + 5
            while True:
                try:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise PipperError("Outra operação do Pipper está em andamento. Tente novamente.")
                    time.sleep(.05)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def settings(self) -> MonitorSettings:
        return self.vnc.running_settings() or self.manager.read_profile()

    def start(self, settings: MonitorSettings, environment: Environment):
        environment.require_hyprland()
        with self.lock():
            self._start(settings)

    def _start(self, settings: MonitorSettings):
        settings, _ = settings.validated()
        existing = self.vnc.running_settings()
        if existing and existing.output != settings.output:
            raise PipperError(f"{existing.output} já está ligado. Desligue essa sessão antes de trocar o dispositivo.")
        if self.vnc.is_running(settings.output):
            return
        self.manager.save_profile(settings)
        created = False
        try:
            created = self.hypr.ensure_output(settings)
            if not created:
                self.hypr.configure(settings)
            self.hypr.activate_workspace(settings)
            self.vnc.start(settings)
            self.hypr.temporary_outputs.discard(settings.output)
        except Exception:
            if created:
                self.hypr.remove_output(settings.output)
            raise

    def stop(self, output: str, environment: Environment):
        environment.require_hyprland()
        with self.lock():
            self.vnc.stop(output)
            self.hypr.remove_output(output)

    def toggle(self, environment: Environment) -> str:
        # The decision and mutation must be atomic across UI/launcher processes.
        environment.require_hyprland()
        with self.lock():
            settings = self.settings()
            if self.vnc.is_running(settings.output):
                self.vnc.stop(settings.output)
                self.hypr.remove_output(settings.output)
                return f"{settings.output} desligado."
            self._start(settings)
            return f"{settings.output} ligado no workspace {settings.workspace}."

    def focus(self, environment: Environment):
        environment.require_hyprland()
        settings = self.settings()
        if not self.vnc.is_running(settings.output):
            raise PipperError("Ligue Pipper antes de acessar o workspace do celular.")
        self.hypr.focus_workspace(settings)
        return f"Workspace {settings.workspace} do celular ativado."

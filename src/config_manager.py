"""System integration independent of GTK. Commands never run through a shell."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import fnmatch
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import tomllib
from typing import Callable


LAYERS = {
    "bar.default": "Barra Superior", "dock": "Dock",
    "notifications": "Notificações", "osd": "Popups de Volume/Brilho",
    "mpris": "Player de Música",
}

EDITORS = {"auto": "Automático", "hyprmon": "Hyprmon · Kitty",
           "nwg-displays": "nwg-displays", "wdisplays": "wdisplays",
           "custom": "Comando personalizado"}


def editor_command(editor: str = "auto", custom_command: str = "") -> list[str]:
    """Resolve an executable and arguments before touching the compositor."""
    if editor == "auto":
        editor = next((name for name in ("hyprmon", "nwg-displays", "wdisplays")
                       if shutil.which(name) and (name != "hyprmon" or shutil.which("kitty"))), "")
        if not editor:
            raise PipperError("Escolha um editor instalado ou informe um comando personalizado na aba Posição.")
    if editor == "hyprmon":
        for program in ("kitty", "hyprmon"):
            if not shutil.which(program):
                raise PipperError(f"Instale {program} para usar Hyprmon no Kitty.")
        return ["kitty", "-e", "hyprmon"]
    if editor in ("nwg-displays", "wdisplays"):
        if not shutil.which(editor):
            raise PipperError(f"Editor não instalado: {editor}. Escolha outro na aba Posição.")
        return [editor]
    if editor == "custom":
        try:
            args = shlex.split(custom_command)
        except ValueError as exc:
            raise PipperError(f"Comando inválido: {exc}") from exc
        if not args:
            raise PipperError("Informe o comando do editor. Exemplo: kitty -e hyprmon.")
        if not shutil.which(args[0]):
            raise PipperError(f"Programa não encontrado: {args[0]}.")
        return args
    raise PipperError("Editor desconhecido. Escolha uma das opções disponíveis.")


class PipperError(RuntimeError):
    """An actionable error suitable for the application status area."""


@dataclass(frozen=True)
class MonitorSettings:
    output: str = "S22"
    resolution: str = "1920x1080"
    refresh: str = "60"
    position: str = "3552x1376"
    scale: str = "2.0"
    workspace: str = "11"

    @property
    def mode(self) -> str:
        return f"{self.resolution}@{self.refresh}"

    @classmethod
    def from_preset(cls, preset: dict) -> MonitorSettings:
        return cls(**{key: str(preset[key]) for key in cls.__dataclass_fields__})

    def validated(self) -> tuple[MonitorSettings, str | None]:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", self.output):
            raise PipperError("Output: use letras, números, ponto, hífen ou sublinhado (até 64 caracteres).")
        match = re.fullmatch(r"([1-9]\d{0,4})x([1-9]\d{0,4})", self.resolution)
        if not match:
            raise PipperError("Resolução inválida. Exemplo: 1920x1080.")
        width, height = map(int, match.groups())
        if not re.fullmatch(r"-?\d{1,6}x-?\d{1,6}", self.position):
            raise PipperError("Posição inválida. Exemplo: 3552x1376 ou -1920x0.")
        if not re.fullmatch(r"[1-9]\d{0,4}", self.workspace):
            raise PipperError("Workspace: informe um número inteiro positivo até 99999.")
        try:
            refresh, scale = Decimal(self.refresh), Decimal(self.scale)
        except InvalidOperation as exc:
            raise PipperError("Taxa e escala devem ser números. Use ponto decimal.") from exc
        if not refresh.is_finite() or not Decimal(1) <= refresh <= Decimal(1000):
            raise PipperError("Taxa de atualização deve estar entre 1 e 1000 Hz.")
        if not scale.is_finite() or not Decimal("0.25") <= scale <= Decimal(10):
            raise PipperError("Escala deve estar entre 0.25 e 10.")
        adjusted = nearest_scale(width, height, scale)
        warning = None
        if adjusted != scale:
            warning = (f"Escala {scale} ajustada para {adjusted}: a área lógica precisa "
                       "ter largura e altura inteiras.")
        return replace(self, scale=str(adjusted), refresh=str(refresh)), warning


def nearest_scale(width: int, height: int, requested: Decimal) -> Decimal:
    """Exact rational divisibility; corrections use practical 0.01 scale steps.

    Keep any already-valid value, even with more than two decimal places.
    Infinite repeating decimal divisors cannot be expressed exactly in the UI.
    """
    value = Fraction(requested)
    if (Fraction(width) / value).denominator == (Fraction(height) / value).denominator == 1:
        return requested
    candidates = [Decimal(tick) / 100 for tick in range(25, 1001)
                  if (width * 100) % tick == 0 and (height * 100) % tick == 0]
    return min(candidates, key=lambda candidate: (abs(candidate - requested), -candidate))


def run_command(args: list[str], timeout: float = 12) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise PipperError(f"Comando não instalado: {args[0]}.") from exc
    except subprocess.TimeoutExpired as exc:
        raise PipperError(f"O comando {args[0]} não respondeu em {timeout:g}s.") from exc
    if result.returncode:
        raise PipperError((result.stderr or result.stdout).strip() or f"Falha em {args[0]}.")
    output = result.stdout.strip()
    # hyprctl may return success at the OS level for a compositor-side error.
    if args[0] == "hyprctl" and len(args) > 1 and args[1] in {"eval", "keyword", "output", "dispatch"}:
        if output.lower() != "ok":
            raise PipperError(output)
    return output


def atomic_write(path: Path, content: str, original: str | None, backup_dir: Path | None = None) -> Path | None:
    """Preserve symlinks, permissions and a timestamped backup; detect concurrent edits."""
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    current = path.read_text() if path.exists() else None
    if current != original:
        raise PipperError(f"{path.name} mudou durante a edição. Tente novamente.")
    if current == content:
        return None
    backup = None
    if path.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup = (backup_dir or path.parent) / f"{path.name}.pipper-{stamp}.bak"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup)
    descriptor, name = tempfile.mkstemp(prefix=".pipper-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, path.stat().st_mode & 0o777 if path.exists() else 0o600)
        if (path.read_text() if path.exists() else None) != original:
            raise PipperError(f"{path.name} mudou durante a edição. Tente novamente.")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return backup


def lua_rules(settings: MonitorSettings) -> str:
    # All interpolated values pass strict allowlists in validated().
    settings, _ = settings.validated()
    return (f'hl.monitor({{ output = "{settings.output}", mode = "{settings.mode}", '
            f'position = "{settings.position}", scale = {settings.scale} }})\n'
            f'hl.workspace_rule({{ workspace = "{settings.workspace}", '
            f'monitor = "{settings.output}", default = true }})')


class ConfigManager:
    def __init__(self, config_home: Path | None = None):
        root = config_home or Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        self.hypr_dir = root / "hypr"
        noctalia_root = Path(os.environ.get("NOCTALIA_CONFIG_HOME", root)) if config_home is None else root
        self.noctalia_path = noctalia_root / "noctalia/config.toml"
        self.preferences_path = root / "pipper/preferences.json"
        self.profile_path = root / "pipper/device.json"

    def read_profile(self) -> MonitorSettings:
        if not self.profile_path.exists():
            return self.read_hypr(MonitorSettings())
        try:
            settings, _ = MonitorSettings(**json.loads(self.profile_path.read_text())).validated()
            return settings
        except (ValueError, TypeError) as exc:
            raise PipperError("O perfil salvo do Pipper é inválido. Salve novamente pela interface.") from exc

    def save_profile(self, settings: MonitorSettings):
        settings, _ = settings.validated()
        original = self.profile_path.read_text() if self.profile_path.exists() else None
        content = json.dumps(settings.__dict__, ensure_ascii=False, indent=2) + "\n"
        atomic_write(self.profile_path, content, original)

    def read_preferences(self) -> dict[str, str]:
        if not self.preferences_path.exists():
            return {"editor": "auto", "custom_command": ""}
        try:
            document = json.loads(self.preferences_path.read_text())
            if not isinstance(document, dict):
                raise ValueError("Expected an object")
            editor = document.get("editor", "auto")
            custom = document.get("custom_command", "")
            if editor not in EDITORS or not isinstance(custom, str):
                raise ValueError("Invalid editor preference")
            return {"editor": editor, "custom_command": custom}
        except (ValueError, TypeError) as exc:
            raise PipperError("Preferências do Pipper inválidas. Escolha novamente o editor na aba Posição.") from exc

    def save_preferences(self, editor: str, custom_command: str):
        if editor not in EDITORS:
            raise PipperError("Editor desconhecido.")
        original = self.preferences_path.read_text() if self.preferences_path.exists() else None
        content = json.dumps({"editor": editor, "custom_command": custom_command}, ensure_ascii=False, indent=2) + "\n"
        atomic_write(self.preferences_path, content, original)

    @property
    def hypr_path(self) -> Path:
        lua = self.hypr_dir / "hyprland.lua"
        conf = self.hypr_dir / "hyprland.conf"
        return conf if not lua.exists() and conf.exists() else lua

    def _hypr_sources(self) -> list[tuple[Path, str]]:
        """Read literal local includes in order, without evaluating user Lua."""
        sources, seen = [], set()

        def visit(path: Path):
            path = path.expanduser().resolve()
            if path in seen or len(seen) >= 64 or not path.is_file():
                return
            seen.add(path)
            content = path.read_text()
            if path.suffix == ".lua":
                content = re.sub(r"--\[\[.*?\]\]|--[^\n]*", "", content, flags=re.S)
            cursor = 0
            include = re.compile(r'(?:require|dofile)\s*\(\s*["\']([^"\']+)["\']\s*\)|^\s*source\s*=\s*(.+)$', re.M)
            for match in include.finditer(content):
                sources.append((path, content[cursor:match.start()]))
                cursor = match.end()
                module = match.group(1)
                if module:
                    if content[match.start():].startswith("require"):
                        candidates = [self.hypr_dir / (module.replace(".", "/") + ".lua"),
                                      self.hypr_dir / module.replace(".", "/") / "init.lua"]
                    else:
                        target = Path(os.path.expandvars(module)).expanduser()
                        candidates = [target if target.is_absolute() else path.parent / target]
                else:
                    target = Path(os.path.expandvars(match.group(2).strip())).expanduser()
                    candidates = [target if target.is_absolute() else path.parent / target]
                for candidate in candidates:
                    # Discovery intentionally stays within the Hyprland config tree.
                    if candidate.resolve().is_relative_to(self.hypr_dir.resolve()) and candidate.exists():
                        visit(candidate)
                        break
            sources.append((path, content[cursor:]))

        visit(self.hypr_path)
        return sources

    def read_hypr(self, settings: MonitorSettings) -> MonitorSettings:
        updates = {}
        for path, text in self._hypr_sources():
            if path.suffix == ".lua":
                text = re.sub(r"--\[\[.*?\]\]|--[^\n]*", "", text, flags=re.S)
                for match in re.finditer(r"hl\.(monitor|workspace_rule)\s*\(\s*\{([^}]+)\}\s*\)", text, re.S):
                    values = {}
                    for key, quoted, numeric in re.findall(r'([\w]+)\s*=\s*(?:["\']([^"\']*)["\']|([\d.]+))', match.group(2)):
                        values[key] = quoted or numeric
                    if match.group(1) == "monitor" and values.get("output") == settings.output:
                        if re.fullmatch(r"\d+x\d+@[\d.]+", values.get("mode", "")):
                            updates["resolution"], updates["refresh"] = values["mode"].split("@")
                        for key in ("position", "scale"):
                            if key in values:
                                updates[key] = values[key]
                    elif match.group(1) == "workspace_rule" and values.get("monitor") == settings.output:
                        if values.get("workspace", "").isdigit():
                            updates["workspace"] = values["workspace"]
            else:
                for line in text.splitlines():
                    line = line.split("#", 1)[0]
                    if match := re.match(r"\s*monitor\s*=\s*(.+)", line):
                        fields = [field.strip() for field in match[1].split(",")]
                        if len(fields) >= 4 and fields[0] == settings.output and "@" in fields[1]:
                            updates["resolution"], updates["refresh"] = fields[1].split("@", 1)
                            updates.update(position=fields[2], scale=fields[3])
                    if match := re.match(r"\s*workspace\s*=\s*(\d+)\s*,.*monitor:([^,\s]+)", line):
                        if match[2] == settings.output:
                            updates["workspace"] = match[1]
        return replace(settings, **updates)

    def save_hypr(self, settings: MonitorSettings) -> Path | None:
        settings, _ = settings.validated()
        path = self.hypr_path
        original = path.read_text() if path.exists() else None
        lua = path.suffix == ".lua"
        prefix = "--" if lua else "#"
        start, end = f"{prefix} [PIPPER START]", f"{prefix} [PIPPER END]"
        body = lua_rules(settings) if lua else (
            f"monitor = {settings.output},{settings.mode},{settings.position},{settings.scale}\n"
            f"workspace = {settings.workspace},monitor:{settings.output},default:true")
        text = original or ""
        if text.count(start) != text.count(end) or text.count(start) > 1:
            raise PipperError("Bloco PIPPER incompleto ou duplicado. Corrija os marcadores antes de salvar.")
        if start in text:
            if text.index(end) < text.index(start):
                raise PipperError("Os marcadores PIPPER estão fora de ordem.")
            text = re.sub(re.escape(start) + r".*?" + re.escape(end), "", text, flags=re.S)
        # Append so includes before the block cannot override the saved rule.
        text = text.rstrip() + ("\n\n" if text.strip() else "") + f"{start}\n{body}\n{end}\n"
        return atomic_write(path, text, original)

    def _noctalia(self) -> tuple[str | None, dict]:
        original = self.noctalia_path.read_text() if self.noctalia_path.exists() else None
        try:
            return original, tomllib.loads(original or "")
        except tomllib.TOMLDecodeError as exc:
            raise PipperError(f"Noctalia: TOML inválido; arquivo preservado. {exc}") from exc

    @staticmethod
    def _layer_rules(document: dict, layer: str) -> dict:
        section = document
        for part in layer.split("."):
            section = section.get(part, {})
            if not isinstance(section, dict):
                raise PipperError(f"Noctalia: a seção {layer} não é uma tabela TOML.")
        rules = section.get("monitor", {})
        if not isinstance(rules, dict):
            raise PipperError(f"Noctalia: {layer}.monitor não é uma tabela TOML.")
        return rules

    def read_exclusions(self, output: str) -> dict[str, bool]:
        _, document = self._noctalia()
        result = {}
        for layer in LAYERS:
            matches = [rule for rule in self._layer_rules(document, layer).values()
                       if isinstance(rule, dict) and isinstance(rule.get("match"), str)
                       and fnmatch.fnmatchcase(output, rule["match"])]
            result[layer] = any(rule.get("enabled") is False for rule in matches)
        return result

    def save_exclusions(self, output: str, exclusions: dict[str, bool]) -> Path | None:
        MonitorSettings(output=output).validated()
        original, document = self._noctalia()
        try:
            import tomlkit
        except ImportError as exc:
            raise PipperError("Instale python-tomlkit para editar Noctalia preservando comentários.") from exc
        editable = tomlkit.parse(original or "")
        for layer in LAYERS:
            if layer not in exclusions:
                continue
            section = editable
            for key in (*layer.split("."), "monitor"):
                if key not in section:
                    section[key] = tomlkit.table()
                section = section[key]
            # Recognize/update existing exact aliases (celular, telemovel, ...).
            # Wildcard rules are left intact because they can affect other monitors.
            for rule in section.values():
                if isinstance(rule, dict) and rule.get("match") == output:
                    rule["enabled"] = not exclusions[layer]
            if "pipper" not in section:
                section["pipper"] = tomlkit.table()
            section["pipper"]["match"] = output
            section["pipper"]["enabled"] = not exclusions[layer]
        content = tomlkit.dumps(editable)
        tomllib.loads(content)
        return atomic_write(self.noctalia_path, content, original)


class HyprlandController:
    def __init__(self, runner: Callable = run_command, pause: Callable = time.sleep):
        self.run = runner
        self.pause = pause
        self.temporary_outputs: set[str] = set()

    def monitors(self, all_outputs: bool = True) -> list[dict]:
        args = ["hyprctl", "monitors"] + (["all"] if all_outputs else []) + ["-j"]
        try:
            result = json.loads(self.run(args))
            if not isinstance(result, list) or any(not isinstance(item, dict) for item in result):
                raise ValueError("Expected a monitor list")
            return result
        except (ValueError, TypeError) as exc:
            raise PipperError("Não foi possível ler os monitores. Abra Pipper dentro da sessão Hyprland.") from exc

    def sync(self, settings: MonitorSettings) -> MonitorSettings:
        monitor = next((m for m in self.monitors(False) if m.get("name") == settings.output), None)
        if not monitor:
            raise PipperError(f"Monitor {settings.output} não está ativo.")
        return replace(settings, position=f'{monitor["x"]}x{monitor["y"]}', scale=str(monitor["scale"]))

    def discover(self, settings: MonitorSettings) -> MonitorSettings:
        monitor = next((m for m in self.monitors() if m.get("name") == settings.output), None)
        if not monitor:
            return settings
        updates = {}
        if monitor.get("width", 0) > 0 and monitor.get("height", 0) > 0:
            updates.update(resolution=f'{monitor["width"]}x{monitor["height"]}',
                           refresh=format(float(monitor.get("refreshRate", 60)), ".3f").rstrip("0").rstrip("."))
        if "x" in monitor and "y" in monitor:
            updates["position"] = f'{monitor["x"]}x{monitor["y"]}'
        if monitor.get("scale", 0) > 0:
            updates["scale"] = str(monitor["scale"])
        # The currently displayed workspace can change independently of the
        # user's configured target. Keep the saved/session target on discovery.
        return replace(settings, **updates)

    def ensure_output(self, settings: MonitorSettings, temporary: bool = False) -> bool:
        settings, _ = settings.validated()
        if any(m.get("name") == settings.output for m in self.monitors()):
            return False
        before = {m.get("name") for m in self.monitors()}
        self.run(["hyprctl", "output", "create", "headless", settings.output])
        self.pause(0.8)
        monitors = self.monitors()
        if not any(m.get("name") == settings.output for m in monitors):
            # Older backends ignore the custom name: do not silently use the wrong output.
            created = [m.get("name") for m in monitors if m.get("name") not in before]
            for name in created:
                if name and name.startswith("HEADLESS-"):
                    self.run(["hyprctl", "output", "remove", name])
            raise PipperError(f"Hyprland não criou o output com nome {settings.output}. Atualize o compositor para suporte a outputs nomeados.")
        self.temporary_outputs.add(settings.output)
        try:
            self.configure(settings)
        except Exception:
            self.remove_output(settings.output)
            raise
        if not temporary:
            self.temporary_outputs.discard(settings.output)
        return True

    def configure(self, settings: MonitorSettings):
        settings, _ = settings.validated()
        for rule in lua_rules(settings).splitlines():
            self.run(["hyprctl", "eval", rule])

    def activate_workspace(self, settings: MonitorSettings):
        settings, _ = settings.validated()
        # Current Lua API plus the compatibility API used by earlier Lua versions.
        move = (f'if hl.dsp and hl.dsp.workspace then hl.dispatch(hl.dsp.workspace.move({{ '
                f'workspace = "{settings.workspace}", monitor = "{settings.output}" }})) '
                f'else hl.dispatch("moveworkspacetomonitor", "{settings.workspace} {settings.output}") end')
        focus = (f'if hl.dsp and hl.dsp.focus then hl.dispatch(hl.dsp.focus({{ workspace = "{settings.workspace}" }})) '
                 f'else hl.dispatch("workspace", "{settings.workspace}") end')
        # Ensure a never-before-used workspace exists before moving it.
        self.run(["hyprctl", "eval", focus])
        self.run(["hyprctl", "eval", move])

    def focus_workspace(self, settings: MonitorSettings):
        settings, _ = settings.validated()
        self.run(["hyprctl", "eval", (
            f'if hl.dsp and hl.dsp.focus then hl.dispatch(hl.dsp.focus({{ workspace = "{settings.workspace}" }})) '
            f'else hl.dispatch("workspace", "{settings.workspace}") end')])

    def remove_output(self, output: str):
        MonitorSettings(output=output).validated()
        if any(m.get("name") == output for m in self.monitors()):
            self.run(["hyprctl", "output", "remove", output])
        self.temporary_outputs.discard(output)

    def editor(self, settings: MonitorSettings, editor: str = "auto", custom_command: str = "") -> tuple[subprocess.Popen, bool]:
        args = editor_command(editor, custom_command)
        created = self.ensure_output(settings, temporary=True)
        try:
            return subprocess.Popen(args), created
        except OSError as exc:
            if created:
                self.remove_output(settings.output)
            raise PipperError(f"Não foi possível abrir {args[0]}: {exc}") from exc


class WayVNCManager:
    """Own the child and only stop other same-user wayvnc instances for this output."""
    def __init__(self, state_dir: Path | None = None):
        self.state_dir = state_dir or Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "pipper"
        self.process: subprocess.Popen | None = None
        self.output: str | None = None

    @property
    def log_path(self) -> Path:
        return self.state_dir / "wayvnc.log"

    @property
    def session_path(self) -> Path:
        return self.state_dir / "session.json"

    def running_settings(self) -> MonitorSettings | None:
        """Recover an unsaved device selection when reopening the UI."""
        if not self.session_path.exists():
            return None
        try:
            document = json.loads(self.session_path.read_text())
            settings, _ = MonitorSettings(**document).validated()
        except (ValueError, TypeError, PipperError) as exc:
            raise PipperError("Registro da sessão inválido. Verifique o arquivo session.json do Pipper.") from exc
        return settings if self.is_running(settings.output) else None

    def _forget_session(self, output: str):
        if not self.session_path.exists():
            return
        try:
            document = json.loads(self.session_path.read_text())
        except ValueError:
            return
        if isinstance(document, dict) and document.get("output") == output:
            self.session_path.unlink(missing_ok=True)

    @staticmethod
    def matching_processes(output: str) -> list[tuple[int, str]]:
        matches = []
        for path in Path("/proc").glob("[0-9]*"):
            try:
                if path.stat().st_uid != os.getuid():
                    continue
                args = (path / "cmdline").read_bytes().decode().strip("\0").split("\0")
                if not args or Path(args[0]).name != "wayvnc":
                    continue
                selected = None
                for i, arg in enumerate(args):
                    if arg.startswith("--output="):
                        selected = arg.split("=", 1)[1]
                    elif arg in ("--output", "-o") and i + 1 < len(args):
                        selected = args[i + 1]
                if selected == output:
                    keys = [key for key in ("WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE", "XDG_RUNTIME_DIR") if os.environ.get(key)]
                    if keys:
                        process_env = dict(item.split("=", 1) for item in (path / "environ").read_bytes().decode().split("\0") if "=" in item)
                        if any(process_env.get(key) != os.environ[key] for key in keys):
                            continue
                    start_time = (path / "stat").read_text().rsplit(")", 1)[1].split()[19]
                    matches.append((int(path.name), start_time))
            except (OSError, UnicodeError, IndexError):
                continue
        return matches

    def is_running(self, output: str) -> bool:
        return bool(self.matching_processes(output))

    def stop(self, output: str):
        processes = self.matching_processes(output)
        for pid, _ in processes:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and self.matching_processes(output):
            if self.process:
                self.process.poll()  # Reap a terminated owned child.
            time.sleep(0.05)
        for pid, start in processes:
            if (pid, start) in self.matching_processes(output):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        if self.process and self.output == output:
            self.process.wait(timeout=3)
            self.process = None
        if self.output == output:
            self.output = None
        self._forget_session(output)

    def start(self, settings: MonitorSettings):
        settings, _ = settings.validated()
        if not shutil.which("wayvnc"):
            raise PipperError("Instale wayvnc antes de ligar Pipper.")
        self.stop(settings.output)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        args = ["wayvnc", f"--output={settings.output}", f"--max-fps={int(Decimal(settings.refresh))}", "0.0.0.0", "5900"]
        with self.log_path.open("w") as log:
            self.process = subprocess.Popen(args, stdin=subprocess.DEVNULL,
                                            stdout=log, stderr=log, start_new_session=True)
        self.output = settings.output
        time.sleep(0.5)
        if self.process.poll() is not None:
            detail = self.log_path.read_text().strip()[-1600:]
            self.process = None
            self.output = None
            raise PipperError(f"wayvnc não iniciou: {detail or 'verifique a porta 5900 e a sessão Wayland.'}")
        try:
            original = self.session_path.read_text() if self.session_path.exists() else None
            content = json.dumps({key: getattr(settings, key) for key in settings.__dataclass_fields__}, indent=2) + "\n"
            atomic_write(self.session_path, content, original)
        except Exception:
            self.stop(settings.output)
            raise


def dependency_status() -> dict[str, bool]:
    result = {name: shutil.which(name) is not None for name in ("hyprctl", "wayvnc", "nwg-displays", "wdisplays", "hyprmon", "kitty")}
    if shutil.which("pacman"):
        for package in ("wayvnc", "nwg-displays"):
            try:
                run_command(["pacman", "-Qi", package], timeout=5)
            except PipperError:
                result[package] = False
    try:
        import tomlkit  # noqa: F401
        result["python-tomlkit"] = True
    except ImportError:
        result["python-tomlkit"] = False
    return result


def install_dependencies(packages: list[str] | None = None) -> subprocess.Popen:
    if not shutil.which("pacman"):
        raise PipperError("Instalação automática disponível no Arch Linux. Veja as instruções no README.")
    terminal = next((program for program in ("kitty", "foot", "alacritty", "xterm") if shutil.which(program)), None)
    if not terminal:
        raise PipperError("Instale um terminal (kitty, foot, alacritty ou xterm).")
    packages = ["wayvnc", "nwg-displays", "python-tomlkit"] if packages is None else packages
    if not packages or any(package not in {"wayvnc", "nwg-displays", "python-tomlkit"} for package in packages):
        raise PipperError("Não há dependências compatíveis para instalar nesta sessão.")
    return subprocess.Popen([terminal, "-e", "sudo", "pacman", "-S", "--needed", *packages])


def local_addresses() -> list[str]:
    """Prefer the LAN default route; no packet is sent by UDP connect()."""
    found = []
    if shutil.which("ip"):
        try:
            routes = json.loads(run_command(["ip", "-j", "route", "get", "1.1.1.1"], timeout=3))
            found.extend(route.get("prefsrc", "") for route in routes)
            interfaces = json.loads(run_command(["ip", "-j", "-4", "address", "show", "up"], timeout=3))
            for interface in interfaces:
                found.extend(address.get("local", "") for address in interface.get("addr_info", [])
                             if address.get("scope") == "global")
        except (PipperError, ValueError):
            pass
    if not found:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(2)
                sock.connect(("1.1.1.1", 80))
                found.append(sock.getsockname()[0])
        except OSError:
            pass
    valid = []
    for address in found:
        try:
            parsed = ipaddress.ip_address(address)
            if parsed.version == 4 and not parsed.is_loopback and not parsed.is_unspecified and address not in valid:
                valid.append(address)
        except ValueError:
            pass
    return valid

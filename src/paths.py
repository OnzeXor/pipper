"""Locate resources in a checkout, wheel, venv or staged system package."""
from pathlib import Path
import sys


def checkout_root() -> Path | None:
    root = Path(__file__).resolve().parent.parent
    return root if (root / "pipper").is_file() and (root / "data/icons/pipper.svg").is_file() else None


def data_directory() -> Path:
    root = checkout_root()
    if root:
        return root / "data"
    # Resolve relative to the module first so a staged /usr install can be
    # verified without installing anything on the developer's machine.
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "share/pipper"
        if (candidate / "icons/pipper.svg").is_file():
            return candidate
    return Path(sys.prefix) / "share/pipper"


def command_argv() -> list[str]:
    root = checkout_root()
    if root:
        return [sys.executable, str(root / "pipper")]
    return [sys.executable, "-m", __package__.split(".", 1)[0]]


def icon_path() -> Path:
    directory = data_directory() / "icons"
    sized = directory / "hicolor/256x256/apps/pipper.png"
    return sized if sized.is_file() else directory / "pipper.png"

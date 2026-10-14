#!/usr/bin/env python3
"""Export only public project files, without any Git history or credentials."""
import hashlib
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import __version__

ROOT_FILES = {"README.md", "LICENSE", "CHANGELOG.md", "CONTRIBUTING.md", "pyproject.toml", "MANIFEST.in",
              "requirements.txt", "PKGBUILD", ".SRCINFO", ".gitignore", "pipper"}
DIRECTORIES = ("src", "data", "docs", "scripts", "tests", "packaging", ".github")
EXCLUDED = {"__pycache__", ".git", ".aws", ".codex", ".agents", "previous"}


def public_files():
    for name in sorted(ROOT_FILES):
        path = ROOT / name
        if path.is_file() and not path.is_symlink():
            yield path
    for name in DIRECTORIES:
        for path in sorted((ROOT / name).rglob("*")):
            relative = path.relative_to(ROOT)
            if not path.is_file() or path.is_symlink() or set(relative.parts) & EXCLUDED:
                continue
            if path.suffix in {".pyc", ".pyo", ".bak", ".log"} or path.name.startswith(".env"):
                continue
            yield path


def main():
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    archive = output / f"pipper-{__version__}-github-ready.zip"
    files = list(public_files())
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as package:
        for path in files:
            package.write(path, Path("pipper") / path.relative_to(ROOT))
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{checksum}  {archive.name}\n")
    print(f"{archive}\n{len(files)} arquivos; sem histórico Git, credenciais ou publicações.")


if __name__ == "__main__":
    main()

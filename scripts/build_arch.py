#!/usr/bin/env python3
"""Build locally; never install a package or communicate with GitHub."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import __version__


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-archive", type=Path, help="Use an existing source archive instead of rebuilding it")
    parser.add_argument("--output", type=Path, default=ROOT / "dist/arch")
    args = parser.parse_args()
    if os.getuid() == 0:
        parser.error("Execute como usuário comum. makepkg não deve ser executado como root.")
    if not shutil.which("makepkg"):
        parser.error("makepkg não foi encontrado. Este comando requer Arch Linux ou derivado.")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if args.source_archive:
        archive = args.source_archive.resolve()
    else:
        subprocess.run([sys.executable, "-m", "build", "--sdist", "--no-isolation", "--outdir", str(ROOT / "dist"), str(ROOT)], check=True)
        archive = ROOT / "dist" / f"pipper-{__version__}.tar.gz"
    if archive.name != f"pipper-{__version__}.tar.gz" or not archive.is_file():
        parser.error(f"Informe o arquivo pipper-{__version__}.tar.gz gerado deste projeto.")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    recipe = (ROOT / "PKGBUILD").read_text()
    recipe = re.sub(r"^pkgver=.*$", f"pkgver={__version__}", recipe, flags=re.M)
    recipe = re.sub(r"^sha256sums=.*$", f"sha256sums=('{digest}')", recipe, flags=re.M)
    with tempfile.TemporaryDirectory(prefix="pipper-makepkg-") as directory:
        work = Path(directory)
        (work / "PKGBUILD").write_text(recipe)
        shutil.copy2(archive, work / archive.name)
        config = ("source /etc/makepkg.conf\n"
                  f"PKGDEST={shlex.quote(str(output))}\n"
                  f"SRCDEST={shlex.quote(str(work / 'sources'))}\n"
                  f"BUILDDIR={shlex.quote(str(work / 'build'))}\n"
                  "PACKAGER='Pipper contributors'\n"
                  "PKGEXT='.pkg.tar.zst'\n")
        (work / "makepkg.conf").write_text(config)
        subprocess.run(["makepkg", "--config", str(work / "makepkg.conf"), "--cleanbuild", "--force"], cwd=work, check=True)
        info = subprocess.run(["makepkg", "--printsrcinfo"], cwd=work, check=True, capture_output=True, text=True).stdout
        (output / "PKGBUILD").write_text(recipe)
        (output / ".SRCINFO").write_text(info)
        shutil.copy2(archive, output / archive.name)
    artifacts = sorted(output.glob(f"pipper-{__version__}-*.pkg.tar.zst"))
    if not artifacts:
        raise RuntimeError("makepkg encerrou sem gerar o pacote esperado.")
    checksums = "".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in artifacts)
    (output / "SHA256SUMS").write_text(checksums)
    print("\nPacote gerado (não instalado):")
    for path in artifacts:
        print(path)
    print("Para instalar por sua conta: sudo pacman -U <arquivo.pkg.tar.zst>")


if __name__ == "__main__":
    main()

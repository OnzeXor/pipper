#!/usr/bin/env python3
"""Generate a GitHub-release PKGBUILD offline. Does not publish anything."""
import argparse
import hashlib
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import __version__


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True, help="Owner/repository for the FUTURE GitHub destination")
    parser.add_argument("--archive", type=Path, required=True, help="Exact source archive that will be attached to the release")
    parser.add_argument("--output", type=Path, default=ROOT / "dist/release-metadata")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+", args.repository):
        parser.error("Use o formato USUARIO/REPOSITORIO.")
    if args.archive.name != f"pipper-{__version__}.tar.gz" or not args.archive.is_file():
        parser.error(f"Use o source archive pipper-{__version__}.tar.gz gerado pelo projeto.")
    digest = hashlib.sha256(args.archive.read_bytes()).hexdigest()
    recipe = (ROOT / "PKGBUILD").read_text()
    recipe = re.sub(r"^pkgver=.*$", f"pkgver={__version__}", recipe, flags=re.M)
    recipe = re.sub(r"^sha256sums=.*$", f"sha256sums=('{digest}')", recipe, flags=re.M)
    recipe = re.sub(r"^source=.*$", 'source=("pipper-${pkgver}.tar.gz::${url}/releases/download/v${pkgver}/pipper-${pkgver}.tar.gz")', recipe, flags=re.M)
    recipe = recipe.replace("# Local source recipe. Use: python3 scripts/build_arch.py\n# The helper supplies the source archive and its SHA-256 in an isolated folder.\n", "# Release recipe generated locally; publish the referenced source archive first.\n")
    recipe = recipe.replace("pkgname=pipper\n", f"pkgname=pipper\nurl='https://github.com/{args.repository}'\n")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "PKGBUILD").write_text(recipe)
    info = subprocess.run(["makepkg", "--printsrcinfo"], cwd=output, check=True, capture_output=True, text=True).stdout
    (output / ".SRCINFO").write_text(info)
    print(f"PKGBUILD e .SRCINFO gerados em {output}. Nenhum acesso ao GitHub foi realizado.")


if __name__ == "__main__":
    main()

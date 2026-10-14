#!/usr/bin/env bash
# Verified source installation; package dependencies come from the distribution.
set -Eeuo pipefail

install_user() {
    "$python_executable" - "$source_dir" "$version" "$commit" <<'PY'
import json, os, pathlib, shlex, shutil, sys, tempfile

source, version, commit = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
home = pathlib.Path.home()
data = pathlib.Path(os.environ.get('XDG_DATA_HOME') or home / '.local/share')
if not data.is_absolute():
    raise SystemExit('XDG_DATA_HOME precisa ser um caminho absoluto.')
base = data / 'pipper/app'
bin_dir = home / '.local/bin'
desktop = data / 'applications/pipper.desktop'
launcher = bin_dir / 'pipper'
current = base / 'current'
if current.exists() and not current.is_symlink():
    raise SystemExit(f'O caminho {current} já existe e não é um link gerenciado pelo instalador.')
base.mkdir(parents=True, exist_ok=True)
staging = pathlib.Path(tempfile.mkdtemp(prefix='.install-', dir=base))
release = base / (version + '-' + commit[:12] + '-' + staging.name.removeprefix('.install-'))
snapshots = []

def replace_file(path, content, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        previous = (path, 'link', os.readlink(path), 0)
    elif path.exists():
        previous = (path, 'file', path.read_bytes(), path.stat().st_mode & 0o777)
    else:
        previous = (path, 'absent', None, 0)
    fd, temporary = tempfile.mkstemp(prefix='.pipper-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content.encode())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        snapshots.append(previous)
    finally:
        pathlib.Path(temporary).unlink(missing_ok=True)

link = base / ('.current-' + staging.name.removeprefix('.install-'))
try:
    for name in ('src', 'data'):
        shutil.copytree(source / name, staging / name)
    for name in ('pipper', 'LICENSE'):
        shutil.copy2(source / name, staging / name)
    python = shlex.quote(sys.executable)
    entry = shlex.quote(str(current / 'pipper'))
    uninstall = shlex.quote(str(current / 'uninstall.py'))
    wrapper = f'#!/bin/sh\n# Pipper managed installation: {base}\nif [ "${{1-}}" = "--uninstall" ]; then\n  exec {python} {uninstall}\nfi\nexec {python} {entry} "$@"\n'
    # Desktop Entry Exec has its own escaping rules; it is not a shell command.
    executable = str(launcher).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%')
    desktop_text = (source / 'data/pipper.desktop').read_text()
    desktop_text = desktop_text.replace('Exec=pipper', f'Exec="{executable}"')
    desktop_text = desktop_text.replace('Icon=pipper', 'Icon=' + str(current / 'data/icons/pipper.png'))
    metadata = {'version': version, 'commit': commit, 'python': sys.executable}
    (staging / 'installation.json').write_text(json.dumps(metadata, indent=2) + '\n')
    # Removal is scoped to the installed application; preferences and backups
    # live elsewhere and are preserved.
    remover = 'import pathlib, shutil\n'
    remover += f'base = pathlib.Path({str(base)!r})\n'
    remover += f'launcher = pathlib.Path({str(launcher)!r})\n'
    remover += f'desktop = pathlib.Path({str(desktop)!r})\n'
    remover += "if launcher.is_file() and str(base) in launcher.read_text(): launcher.unlink()\n"
    remover += "if desktop.is_file() and str(base) in desktop.read_text(): desktop.unlink()\n"
    remover += "shutil.rmtree(base)\nprint('Pipper removido. Suas preferências foram preservadas.')\n"
    (staging / 'uninstall.py').write_text(remover)
    staging.rename(release)
    replace_file(launcher, wrapper, 0o755)
    replace_file(desktop, desktop_text)
    link.symlink_to(release.name, target_is_directory=True)
    os.replace(link, current)
except BaseException:
    for path, kind, content, mode in reversed(snapshots):
        path.unlink(missing_ok=True)
        if kind == 'link': path.symlink_to(content)
        elif kind == 'file':
            path.write_bytes(content)
            path.chmod(mode)
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(release, ignore_errors=True)
    link.unlink(missing_ok=True)
    raise
print(f'Aplicativo instalado em {current}')
print(f'Comando: {launcher}')
if str(bin_dir) not in os.environ.get('PATH', '').split(os.pathsep):
    print('Abra pelo menu de aplicativos ou pelo caminho acima; ~/.local/bin não está no PATH deste terminal.')
PY
}

main() {
    local version='0.1.0'
    local commit='53ddff964314261cc6cee973b21da74abc52b258'
    local source_sha256='173772542e2812871eb2c95125c4a5f46b0155edd9da773d9cfb067d68ecf83b'
    local source_url="https://codeload.github.com/OnzeXor/pipper/tar.gz/${commit}"
    local preview=false skip_dependencies=false argument
    for argument in "$@"; do
        case "$argument" in
            --help|-h)
                printf '%s\n' 'Pipper — instalador Linux com detecção de distribuição.' \
                    'Uso: bash install.sh [--dry-run] [--skip-dependencies]' \
                    '  --dry-run  Mostrar o plano sem baixar ou instalar.' \
                    '  --skip-dependencies  Usar dependências existentes e instalar somente para o usuário.' \
                    'Arch, Debian/Ubuntu, Fedora, openSUSE, Alpine e Void: dependências automáticas.' \
                    'Outras distribuições e sistemas imutáveis: instalação de usuário se as dependências já estiverem disponíveis.' \
                    'Execute como usuário comum; sudo ou doas é usado apenas pelo gerenciador de pacotes.'
                return 0 ;;
            --dry-run) preview=true ;;
            --skip-dependencies) skip_dependencies=true ;;
            *) printf 'Opção desconhecida: %s\n' "$argument" >&2; return 2 ;;
        esac
    done
    [[ $(uname -s) == Linux ]] || { printf 'O Pipper requer Linux.\n' >&2; return 1; }
    local ID='' ID_LIKE='' PRETTY_NAME='Linux'
    if [[ -r /etc/os-release ]]; then . /etc/os-release; fi
    local family=generic manager='' immutable=false
    case "$ID" in
        nixos|microos|opensuse-microos|aeon|opensuse-aeon|kalpa|opensuse-kalpa|steamos|vanilla|blendos) immutable=true ;;
    esac
    if [[ -e /run/ostree-booted ]] || "$immutable"; then
        immutable=true
    else
        # Match the actual ID first, then its upstream families in order.
        local candidate
        for candidate in "$ID" $ID_LIKE; do
            case "$candidate" in
                arch|manjaro|endeavouros|cachyos) family=arch; manager=pacman; break ;;
                debian|ubuntu|linuxmint|pop|neon) family=debian; manager=apt-get; break ;;
                fedora|rhel|centos|rocky|almalinux) family=fedora; manager=dnf; break ;;
                opensuse*|suse|sles) family=suse; manager=zypper; break ;;
                alpine) family=alpine; manager=apk; break ;;
                void) family=void; manager=xbps-install; break ;;
            esac
        done
    fi
    if "$skip_dependencies"; then family=generic; manager=''; fi
    local packages=()
    case "$family" in
        arch) packages=(base-devel python-build python-installer python-setuptools python-wheel
            python-gobject python-cairo gtk4 python-tomlkit wayvnc 'hyprland>=0.55' desktop-file-utils python-qrcode) ;;
        debian) packages=(python3 python3-gi python3-gi-cairo gir1.2-gtk-4.0 python3-tomlkit python3-qrcode wayvnc desktop-file-utils) ;;
        fedora) packages=(python3 python3-gobject python3-cairo gtk4 python3-tomlkit python3-qrcode wayvnc desktop-file-utils) ;;
        suse) packages=(python3 python3-gobject python3-gobject-Gdk python3-cairo typelib-1_0-Gtk-4_0 libgtk-4-1 python3-tomlkit python3-qrcode wayvnc desktop-file-utils) ;;
        alpine) packages=(python3 py3-gobject3 py3-cairo gtk4.0 py3-tomlkit py3-qrcode wayvnc desktop-file-utils) ;;
        void) packages=(python3 python3-gobject python3-cairo gtk4 python3-tomlkit python3-qrcode wayvnc desktop-file-utils) ;;
    esac
    if "$preview"; then
        printf 'Pipper %s — %s — família: %s\n' "$version" "$PRETTY_NAME" "$family"
        printf 'Baixar: %s\nVerificar SHA-256: %s\n' "$source_url" "$source_sha256"
        case "$family" in
            arch) printf 'Dependências e atualização do sistema: pacman -Syu --needed --' ;;
            debian) printf 'Atualizar índices: apt-get update\nDependências: apt-get install --' ;;
            fedora) printf 'Dependências: dnf install --' ;;
            suse) printf 'Atualizar índices: zypper refresh\nDependências: zypper install --' ;;
            alpine) printf 'Atualizar índices: apk update\nDependências: apk add --' ;;
            void) printf 'Atualizar sistema: xbps-install -Su\nDependências: xbps-install --' ;;
            generic) printf 'Verificar dependências existentes; não alterar pacotes do sistema.' ;;
        esac
        if ((${#packages[@]})); then printf ' %q' "${packages[@]}"; fi
        if [[ $family == arch ]]; then
            printf '\nConstruir e testar como usuário comum; instalar com pacman -U.\n'
        else
            printf '\nInstalar aplicativo em XDG_DATA_HOME/pipper/app e ~/.local/bin/pipper.\n'
        fi
        return 0
    fi
    if [[ $(id -u) == 0 ]]; then
        printf 'Execute como usuário comum, sem sudo antes de bash.\n' >&2; return 1
    fi
    local tool
    for tool in curl sha256sum tar mktemp; do
        command -v "$tool" >/dev/null || { printf 'Comando necessário não encontrado: %s\n' "$tool" >&2; return 1; }
    done
    local privilege=''
    if [[ $family != generic ]]; then
        command -v "$manager" >/dev/null || { printf 'Gerenciador esperado não encontrado: %s\n' "$manager" >&2; return 1; }
        if command -v sudo >/dev/null; then privilege=sudo
        elif command -v doas >/dev/null; then privilege=doas
        else printf 'Configure sudo ou doas para instalar as dependências.\n' >&2; return 1; fi
        # Keep prompts attached to the terminal even when bash reads a pipe.
        if ! { exec 3<>/dev/tty; } 2>/dev/null; then
            printf 'Abra um terminal interativo para informar a senha e confirmar a instalação.\n' >&2; return 1
        fi
    fi
    local work_dir cleanup_command
    work_dir=$(mktemp -d -t pipper-install.XXXXXXXX)
    printf -v cleanup_command 'rm -rf -- %q' "$work_dir"
    trap "$cleanup_command" EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    printf 'Baixando Pipper %s para %s…\n' "$version" "$PRETTY_NAME"
    curl --fail --show-error --location --proto '=https' --tlsv1.2 \
        --connect-timeout 20 --max-time 300 --retry 2 \
        --output "$work_dir/source.tar.gz" "$source_url"
    if ! printf '%s  %s\n' "$source_sha256" "$work_dir/source.tar.gz" | sha256sum -c >/dev/null 2>&1; then
        printf 'A verificação SHA-256 falhou. A instalação foi interrompida antes de usar sudo.\n' >&2; exit 1
    fi
    tar -xzf "$work_dir/source.tar.gz" -C "$work_dir"
    local source_dir="$work_dir/pipper-${commit}"
    [[ -f "$source_dir/pipper" && -f "$source_dir/src/cli.py" && -f "$source_dir/data/pipper.desktop" ]] || {
        printf 'O arquivo fonte não contém os arquivos esperados.\n' >&2; exit 1
    }
    if [[ $family != generic ]]; then
        [[ $privilege != sudo ]] || sudo -v <&3
        printf '\nInstalando dependências com %s…\n' "$manager"
        case "$family" in
            arch) "$privilege" pacman -Syu --needed -- "${packages[@]}" <&3 ;;
            debian) "$privilege" apt-get update <&3; "$privilege" apt-get install -- "${packages[@]}" <&3 ;;
            fedora) "$privilege" dnf install -- "${packages[@]}" <&3 ;;
            suse) "$privilege" zypper refresh <&3; "$privilege" zypper install -- "${packages[@]}" <&3 ;;
            alpine) "$privilege" apk update <&3; "$privilege" apk add -- "${packages[@]}" <&3 ;;
            void) "$privilege" xbps-install -Su <&3; "$privilege" xbps-install -- "${packages[@]}" <&3 ;;
        esac
    fi
    local python_executable=/usr/bin/python3
    [[ -x "$python_executable" ]] || python_executable=$(command -v python3 || true)
    if [[ -z "$python_executable" ]]; then printf 'Python 3.11+ não está disponível.\n' >&2; exit 1; fi
    if [[ $family == arch ]]; then
        printf '\nConstruindo e testando o pacote Arch…\n'
        (cd "$source_dir"; "$python_executable" scripts/build_arch.py --output "$work_dir/packages" <&3)
        local package="$work_dir/packages/pipper-${version}-1-any.pkg.tar.zst"
        [[ -f "$package" ]] || { printf 'A construção não gerou o pacote esperado.\n' >&2; exit 1; }
        "$privilege" pacman -U -- "$package" <&3
    else
        if ! PYTHONNOUSERSITE=1 "$python_executable" -c '
import sys
assert sys.version_info >= (3, 11), "Python 3.11+ necessário"
import gi
assert gi.version_info >= (3, 46), "PyGObject 3.46+ necessário"
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk
import cairo, tomlkit, qrcode
' || ! command -v wayvnc >/dev/null; then
            printf 'Dependências incompletas ou antigas: são necessários Python 3.11+, PyGObject 3.46+, GTK4, Cairo, tomlkit, qrcode e wayvnc.\n' >&2
            if "$immutable"; then printf 'Sistema imutável/NixOS: disponibilize essas dependências pela configuração do sistema antes de instalar.\n' >&2
            elif [[ $family == generic ]]; then printf 'Esta distribuição ainda não tem instalação automática de dependências.\n' >&2
            else printf 'Os repositórios desta versão não forneceram todas as dependências necessárias; nenhum aplicativo foi instalado.\n' >&2; fi
            exit 1
        fi
        PYTHONNOUSERSITE=1 "$python_executable" "$source_dir/pipper" --version
        install_user
    fi
    printf '\nPipper instalado! Abra pelo menu de aplicativos ou execute: pipper\n'
    if [[ $family != arch ]]; then printf 'Para remover o aplicativo: ~/.local/bin/pipper --uninstall\n'; fi
    printf 'A segunda tela requer uma sessão Hyprland compatível; o instalador não troca seu ambiente gráfico.\n'
    exit 0
}

main "$@"

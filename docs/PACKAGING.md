# Empacotamento

[Voltar ao README](../README.md)

## Instalador com curl

O comando do README baixa `scripts/install.sh` da branch `main` de `OnzeXor/pipper`. Para disponibilizá-lo, envie esse arquivo e o README atualizado ao GitHub. O instalador não depende do cadastro no AUR nem de uma release: usa a revisão pública fixa da versão 0.1.0 e verifica o SHA-256 antes de instalar dependências.

Rode `bash scripts/install.sh --dry-run` para conferir o plano sem alterar o sistema. A instalação precisa de Linux, Bash, curl, ferramentas básicas (`tar`, `sha256sum`, `mktemp`) e acesso à internet. A instalação automática de dependências precisa de terminal e sudo ou doas configurado. O usuário ainda confirma as transações do gerenciador de pacotes.

A distribuição é identificada por `ID` e `ID_LIKE` de `/etc/os-release`, dando prioridade ao ID real. O instalador tem rotas para pacman, apt-get, dnf, zypper, apk e xbps-install. Instala GTK/PyGObject, Cairo, tomlkit, qrcode e wayvnc com os nomes de pacote de cada família. Não adiciona repositórios nem tenta substituir versões do Python. O suporte depende da disponibilidade de versões compatíveis nesses repositórios.

No Arch, usa `pacman -Syu --needed`, constrói o pacote como usuário comum e o registra com `pacman -U`. No Void, usa `xbps-install -Su` antes de instalar dependências. Essas rotas atualizam o sistema. Debian/Ubuntu, openSUSE e Alpine atualizam os índices antes de instalar dependências; Fedora usa `dnf install`.

Nas rotas fora do Arch, a aplicação é instalada para o usuário em `$XDG_DATA_HOME/pipper/app` (padrão `~/.local/share/pipper/app`). O launcher fica em `~/.local/bin/pipper`, e a entrada do menu em `$XDG_DATA_HOME/applications/pipper.desktop`, com caminhos absolutos para funcionar sem alterar o PATH. Os ícones são carregados da aplicação. O instalador valida a versão do Python, os imports de GTK/Cairo/tomlkit/qrcode e a presença de wayvnc antes de publicar os arquivos de usuário. O Python do sistema recebe apenas os pacotes do gerenciador nativo, sem pip.

Cada instalação de usuário usa uma pasta própria e troca o link `current` atomicamente. Se a escrita do launcher ou desktop entry falhar, restaura os arquivos anteriores. Versões anteriores são preservadas para não quebrar processos e atalhos já abertos. Remova a instalação com `~/.local/bin/pipper --uninstall`; preferências, estado de sessão e backups do Vicinae não são apagados. A pasta temporária do download é removida também em caso de falha. Dependências instaladas pelo gerenciador são preservadas.

Em NixOS, OSTree/Fedora Atomic e openSUSE Aeon/MicroOS, a rota genérica não altera pacotes do sistema e só instala o aplicativo se os requisitos já estiverem disponíveis. O mesmo vale para distribuições desconhecidas. Você também pode usar `bash scripts/install.sh --skip-dependencies` em qualquer família para escolher essa instalação de usuário. Isso não dispensa os requisitos; eles são verificados antes de instalar.

A aplicação requer Python 3.11+, PyGObject 3.46+, GTK4 e wayvnc. A transmissão continua restrita ao backend Hyprland compatível. O instalador não instala Hyprland fora do pacote Arch nem configura ou troca sua sessão gráfica. O botão de instalar dependências dentro da interface continua sendo uma ferramenta do Arch; nas outras distribuições, execute novamente o instalador para reparar dependências.

Para novas versões, atualize `version`, `commit`, `source_sha256` e, se necessário, a lista de dependências em `scripts/install.sh`. O hash deve ser calculado a partir do arquivo baixado pela URL codeload usada no script. Atualize também a referência e o hash da fixture em `tests/test_installer.py`. Confira o nome de pacote esperado se mudar `pkgrel` ou arquitetura. O instalador não acompanha alterações de `main` no código do aplicativo automaticamente; a revisão fixa garante uma construção identificável.

Os testes automatizados do instalador usam um terminal virtual e serviços substitutos para verificar a execução via pipe, os prompts, o checksum, as seis rotas de gerenciadores, as falhas e a limpeza. Verificam também instalação e remoção de usuário em pastas temporárias, nomes com espaços, preservação de preferências e proteção de sistemas imutáveis. Não executam sudo ou gerenciadores de pacotes reais no host.

Validação em 14/10/2026: dependências reais, verificação do código baixado, instalação de usuário, CLI e desktop entry aprovados em containers descartáveis de Debian 13, Fedora 44, openSUSE Tumbleweed e Alpine 3.23. Nos containers, as dependências foram instaladas pelo administrador do container e o aplicativo foi instalado com `--skip-dependencies`; a execução dos comandos privilegiados pelo instalador foi verificada pelos testes simulados. No Arch, a construção real do pacote e a inspeção do resultado foram verificadas sem instalar o pacote no host. A rota Void foi validada por testes simulados e consulta às receitas oficiais, sem execução em uma instalação real de Void. Esses testes não medem a transmissão VNC nem a integração com uma sessão gráfica real nessas distribuições.

Referências dos nomes de dependências: [PyGObject/GNOME](https://pygobject.gnome.org/getting_started.html), [pacotes do Alpine](https://pkgs.alpinelinux.org/packages), [receitas do Void](https://github.com/void-linux/void-packages/tree/master/srcpkgs).

## Arch Linux

Instale as dependências listadas no README e execute como usuário comum:

```bash
python3 scripts/build_arch.py
```

O script gera o arquivo fonte, calcula SHA-256 e executa `makepkg` em uma pasta temporária. Não instala pacotes, não usa sudo e não acessa GitHub. As dependências precisam estar instaladas antes; o script não usa `makepkg -s`.

Saídas em `dist/arch/`:

- `pipper-0.1.0-1-any.pkg.tar.zst`: pacote instalável.
- `pipper-0.1.0.tar.gz`: fonte exata usada na construção.
- `PKGBUILD` e `.SRCINFO`: receita local correspondente.
- `SHA256SUMS`: checksum do pacote.

Para instalar ou atualizar deliberadamente:

```bash
sudo pacman -U dist/arch/pipper-0.1.0-1-any.pkg.tar.zst
```

Para remover: `sudo pacman -R pipper`. As preferências pessoais são preservadas em seus diretórios XDG.

O PKGBUILD da raiz usa um arquivo fonte local, sem assumir conta ou repositório. Também pode ser usado com `makepkg` depois de colocar o tarball correspondente ao lado dele. O helper recalcula o hash ao reconstruir o fonte. Para uma receita com URL pública, veja [Publicação](PUBLISHING.md).

## Distribuição Python

```bash
python3 -m build --no-isolation
python3 scripts/verify_install.py dist/pipper-0.1.0-py3-none-any.whl
```

A verificação instala a wheel em um prefixo temporário e testa CLI, importação da interface, arquivos de estilo, dispositivos, ícones, desktop entry e scripts do Vicinae fora do checkout. Não altera o Python do sistema. A wheel precisa de GTK4 e PyGObject disponíveis no ambiente; no Arch, prefira o pacote nativo.

O código fonte fica em `src/`, mas o pacote instalado usa o namespace `pipper_app`. Recursos compartilhados são instalados em `/usr/share/pipper` pelo PKGBUILD, e os ícones também vão para o tema hicolor.

## Verificação local

```bash
python3 -m unittest discover -s tests -v
desktop-file-validate data/pipper.desktop
xvfb-run -a env GDK_BACKEND=x11 GSK_RENDERER=cairo python3 tests/gtk_smoke.py
xvfb-run -a env GDK_BACKEND=x11 GSK_RENDERER=cairo python3 tests/gtk_lifecycle.py
xvfb-run -a env GDK_BACKEND=x11 GSK_RENDERER=cairo python3 tests/gtk_environments.py
```

Os testes GTK precisam de `xorg-server-xvfb` e `xorg-xauth`. Usam configurações temporárias e simulam compositor, VNC e serviços. Eles verificam o aplicativo, mas não substituem um teste de transmissão com um celular físico.

Para atualizar o tutorial:

```bash
xvfb-run -a --server-args='-screen 0 1500x1800x24' env GDK_BACKEND=x11 GSK_RENDERER=cairo python3 scripts/capture_tutorial.py
```

O workflow `.github/workflows/build.yml` prepara esses testes e os artefatos em um container Arch quando o projeto for publicado. Não cria releases, tags nem envia pacotes ao AUR. Sua execução no GitHub ainda depende de publicar o repositório e habilitar Actions.

Referências: [diretrizes Python do Arch](https://wiki.archlinux.org/title/Python_package_guidelines), [PKGBUILD](https://man.archlinux.org/man/PKGBUILD.5.en), [makepkg](https://man.archlinux.org/man/makepkg.8.en).

# Empacotamento

[Voltar ao README](../README.md)

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

# Instalação pelo yay e publicação no AUR

[Voltar ao README](../README.md)

Depois de publicar a receita no AUR, a instalação será:

```bash
yay -S pipper
```

Esse comando só estará disponível quando o envio ao AUR tiver sido concluído. O repositório GitHub por si só não registra o pacote no AUR.

As dependências obrigatórias e as de construção estão declaradas no PKGBUILD: o yay resolve a instalação delas, solicitando confirmação e sudo quando necessário. O usuário deve ter o ambiente de construção padrão do Arch (`base-devel`). Python, GTK4, PyGObject, Cairo, tomlkit, wayvnc e Hyprland são dependências obrigatórias. QR Code (`python-qrcode`), editores de posição e Kitty são opcionais; Noctalia e Vicinae não são instalados automaticamente.

## Receita pronta

Os arquivos para envio estão em [`packaging/aur/`](../packaging/aur/). A receita usa uma revisão pública fixa de `OnzeXor/pipper`, com checksum SHA-256, e não depende de uma release ainda não publicada. O download e a construção podem ser testados como usuário comum:

```bash
mkdir -p /tmp/pipper-aur-check
cp packaging/aur/PKGBUILD packaging/aur/.SRCINFO /tmp/pipper-aur-check/
cd /tmp/pipper-aur-check
makepkg -s
```

Não se publica o pacote binário no AUR: enviam-se `PKGBUILD` e `.SRCINFO`.

## Conta e autenticação

Crie uma conta em [aur.archlinux.org](https://aur.archlinux.org/register). A conta é separada do GitHub. Cadastre uma chave SSH pública em **My Account** e use a chave correspondente para autenticar o envio. Não envie sua chave privada por chat.

Se precisar criar uma chave dedicada, escolha um caminho novo:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/pipper-aur
cat ~/.ssh/pipper-aur.pub
```

Copie apenas a linha pública para seu perfil no AUR. Para usar uma chave com outro nome, adapte o caminho nos comandos seguintes.

## Envio inicial

Execute a partir da raiz do projeto, depois de cadastrar a chave:

```bash
git -c core.sshCommand='ssh -i ~/.ssh/pipper-aur -o IdentitiesOnly=yes' clone ssh://aur@aur.archlinux.org/pipper.git /tmp/pipper-aur-publish
```

Se o repositório clonado tiver arquivos ou histórico de outro pacote, pare e confira antes de substituí-los. Se estiver vazio, continue:

```bash
cp packaging/aur/PKGBUILD packaging/aur/.SRCINFO /tmp/pipper-aur-publish/
cd /tmp/pipper-aur-publish
git config core.sshCommand 'ssh -i ~/.ssh/pipper-aur -o IdentitiesOnly=yes'
git config user.name "SEU_NOME"
git config user.email "SEU_EMAIL_PUBLICO"
git branch -M master
git add PKGBUILD .SRCINFO
git commit -m "Add pipper 0.1.0"
git push -u origin master
```

Após o envio, confira a página `https://aur.archlinux.org/packages/pipper` e teste `yay -S pipper`. Para versões novas, atualize a revisão/URL, `pkgver` ou `pkgrel` e o checksum, teste a receita, regenere `.SRCINFO` com `makepkg --printsrcinfo` e publique a atualização.

Referência: [diretrizes oficiais de envio ao AUR](https://wiki.archlinux.org/title/AUR_submission_guidelines_(Portugu%C3%AAs)).

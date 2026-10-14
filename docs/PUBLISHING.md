# Preparar seu GitHub

[Voltar ao README](../README.md)

Este projeto pode ser preparado inteiramente offline. Os comandos de Git e publicação abaixo são instruções para executar depois, com a conta que você escolher.

## 1. Exporte uma pasta limpa

```bash
python3 scripts/export_repository.py
```

O resultado é `dist/pipper-0.1.0-github-ready.zip` e seu checksum. A exportação usa uma lista de diretórios públicos: inclui código, ícones, testes, imagens, documentação e workflow; exclui histórico Git, configurações do Codex, `.aws`, arquivos `.env`, caches, builds e o ícone antigo.

Extraia esse ZIP em uma pasta nova e abra a pasta `pipper`. Assim você começa sem o histórico e sem remotes de outro projeto. Revise a licença MIT incluída e o nome de autoria antes da primeira publicação. O arquivo `LICENSE` está preparado como MIT com autoria genérica “Pipper contributors”.

## 2. Crie um repositório vazio na conta desejada

Entre manualmente no GitHub correto e crie um repositório vazio chamado `pipper`. Os exemplos usam `SEU_USUARIO`; substitua pelo dono real. Confira a conta autenticada no navegador ou no gerenciador de credenciais antes de enviar.

Na pasta extraída, quando estiver pronto para publicar:

```bash
git init -b main
git config user.name "Seu nome"
git config user.email "Seu email de autoria"
git add .
git commit -m "Initial Pipper release"
git remote add origin https://github.com/SEU_USUARIO/pipper.git
git push -u origin main
```

`user.name` e `user.email` definem a autoria do commit; não trocam a conta usada na autenticação. Os scripts do projeto não executam esses comandos nem alteram credenciais.

## 3. Prepare os arquivos de release

Na mesma pasta, construa e valide os artefatos conforme [Empacotamento](PACKAGING.md). Para gerar metadados com a URL do seu repositório:

```bash
python3 scripts/prepare_release.py --repository SEU_USUARIO/pipper --archive dist/pipper-0.1.0.tar.gz
```

O comando só escreve em `dist/release-metadata/`. Gera `PKGBUILD` e `.SRCINFO` com URL da release `v0.1.0` e SHA-256 do arquivo informado. Não faz upload, não cria tag, não publica no AUR e não testa a existência da URL. Use o arquivo fonte exato que será anexado à release; gerar outro tarball pode alterar o checksum.

Depois, crie manualmente uma release com a tag `v0.1.0` e anexe:

- `dist/pipper-0.1.0.tar.gz`, gerado pelo projeto; o arquivo automático “Source code” do GitHub não é substituto para essa URL e esse hash.
- `dist/pipper-0.1.0-py3-none-any.whl`.
- `dist/arch/pipper-0.1.0-1-any.pkg.tar.zst` e `dist/arch/SHA256SUMS`.
- Opcionalmente, `PKGBUILD` e `.SRCINFO` gerados para a URL pública.

A receita pública fica pronta para revisão antes de um eventual envio ao AUR. A preparação local não equivale à publicação ou validação pelo AUR.

## Próximas versões

Atualize `src/__init__.py`, `pkgver` no PKGBUILD e o changelog. Reconstrua todos os artefatos, confira as instruções com a nova versão e gere novamente os metadados a partir do tarball final. Nunca reutilize o hash de uma versão anterior.

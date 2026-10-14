# Contribuir com o Pipper

O desenvolvimento e a revisão podem ser feitos localmente. Não use configurações, IPs ou credenciais pessoais em testes e capturas de tela.

```bash
python3 -m unittest discover -s tests -v
python3 -m build --no-isolation
python3 scripts/verify_install.py dist/pipper-0.1.0-py3-none-any.whl
```

Os testes GTK usam Xvfb e serviços simulados; os comandos estão em [docs/PACKAGING.md](docs/PACKAGING.md). Mudanças de empacotamento devem ser verificadas a partir da wheel instalada em uma pasta temporária, além dos testes do código-fonte.

O pacote Python instalado se chama `pipper_app`; a pasta `src` é o código-fonte do checkout. Use imports relativos dentro do pacote e `src.paths`/`pipper_app.paths` para localizar ícones ou gerar comandos. Não dependa de um caminho pessoal ou da existência de uma cópia Git.

A versão fica em `src/__init__.py`. Ao preparar uma versão, atualize também `pkgver` no `PKGBUILD`, o changelog e os exemplos de nome de arquivo na documentação. Gere o source archive antes de calcular hashes ou preparar o recipe de release.

Por padrão a CI apenas testa e gera artefatos. Publicação de repositórios, tags, releases ou pacotes AUR fica a cargo do mantenedor da conta de destino.

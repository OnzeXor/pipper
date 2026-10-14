# Uso avançado e comportamento

[Voltar ao README](../README.md). Para instalar o pacote, veja [Empacotamento](PACKAGING.md).

## Uso

1. Escolha o dispositivo e ajuste resolução, atualização, escala, posição e **Workspace do celular**. O padrão é **11**; ao ligar, o workspace escolhido é vinculado e movido para o monitor do celular. Para persistir a regra entre sessões, use **Salvar no hyprland.lua**.
2. Clique em **Ligar Pipper**. O output existente é reutilizado; outputs novos são criados e configurados antes de iniciar wayvnc na porta 5900.
3. No celular, conecte AVNC ou RealVNC ao IP mostrado. Ambos os aparelhos precisam estar em uma rede que permita comunicação entre clientes e acesso à porta TCP 5900. Se houver VPN ou múltiplas interfaces, selecione o IP Wi-Fi/LAN acessível pelo celular.
4. Na aba **Posição**, escolha **Hyprmon · Kitty** para abrir `kitty -e hyprmon`, **nwg-displays**, **wdisplays** ou **Comando personalizado**. O modo **Automático** tenta Hyprmon no Kitty primeiro, depois nwg-displays e wdisplays. O editor cria uma tela temporária se necessário. Ao fechar, a posição e escala atuais são sincronizadas; o botão de sincronização também funciona com o editor aberto. A tela temporária fica disponível até ligar Pipper ou fechar o aplicativo.
5. **Salvar no hyprland.lua** mantém as regras de monitor e workspace entre sessões. Os switches do Noctalia são salvos imediatamente com backup.
6. **Desligar Pipper** encerra os processos wayvnc do mesmo usuário associados ao output selecionado e remove a tela virtual. **Fechar o aplicativo mantém a sessão ativa funcionando**: o celular continua conectado e a tela permanece no Hyprland. Reabra o Pipper para controlar a sessão ou desligá-la. Apenas telas temporárias criadas para edição, sem VNC ativo, são removidas ao fechar.

O QR Code é opcional; o endereço `vnc://IP:5900` e as instruções ficam disponíveis mesmo sem `qrcode`. O wayvnc conserva a configuração de autenticação do usuário em `~/.config/wayvnc/config`; o Pipper usa o bind `0.0.0.0` solicitado, permitindo conexões pelas interfaces IPv4.

O wayvnc é iniciado em uma sessão de processo independente, sem entrada padrão herdada da janela. O dispositivo ativo é registrado em `~/.local/state/pipper/session.json`, permitindo reencontrar inclusive uma configuração personalizada que não foi salva no Hyprland. Ao reabrir, o registro só é usado se o processo daquele output ainda estiver ativo. Isso mantém a conexão ao fechar o app durante a sessão atual do Hyprland; não inicia o VNC após logout ou reinício do computador.

O editor escolhido e seu comando são lembrados ao abrir, em `~/.config/pipper/preferences.json`. Comandos personalizados aceitam argumentos e caminhos entre aspas, como `foot -e hyprmon` ou `kitty -e "/opt/meu editor"`. São executados diretamente, sem interpretação de shell; para uma sequência de comandos, selecione um script executável. Se o programa abrir uma janela em outro processo e encerrar imediatamente, use **Sincronizar Posição Atual** depois de ajustar o layout. Hyprmon e Kitty precisam estar instalados para usar a opção dedicada. Referência: [Hyprmon](https://github.com/erans/hyprmon).

## Integrações e conveniências

- **Perfis de transmissão:** Economia (`1280x720@30`, escala `1`), Equilibrado (`1920x1080@60`, escala `2`) e Detalhe (`2560x1440@60`, escala `2.5`). Continuam editáveis e preservam output, posição e workspace.
- **Retrato/paisagem:** troca largura e altura antes de ligar. A escala é validada e a prévia acompanha a orientação.
- **Conexão:** copiar o IP ou o endereço VNC completo; escolha de interface quando houver vários IPs.
- **Hyprland:** botão para focar o workspace do celular e comando de toggle pronto para copiar para um atalho. O menu de aplicativos também oferece as ações de ligar/desligar e focar, se suportado pelo launcher.
- **Vicinae:** com Vicinae e Hyprland ativos, **Adicionar comandos ao Vicinae** cria quatro Script Commands: abrir app, alternar ligado/desligado, focar workspace e mostrar conexão/status. São instalados em `$XDG_DATA_HOME/vicinae/scripts` (padrão `~/.local/share/vicinae/scripts`), com backup antes de atualizar arquivos existentes. O Pipper recarrega o índice com `vicinae cmd launch core:reload-scripts` e confirma os quatro comandos em `vicinae cmd ls --json` antes de mostrar sucesso. A detecção reconhece o processo `vicinae-server`, além de `vicinae`, mantendo a checagem da sessão. O checkout precisa continuar no mesmo caminho. Busque **Pipper**; se a verificação falhar, confira as pastas de scripts do launcher. A geração segue a [documentação de Script Commands](https://docs.vicinae.com/scripts/getting-started).
- **Noctalia v5:** abrir configurações, recarregar configuração e alternar Não Perturbe **no sistema todo**. A aba Aparência também permite ocultar/mostrar todas as camadas no output do celular de uma vez. Arquivos recebem backup e as mudanças são aplicadas com `noctalia msg config-reload`. Se a recarga falhar, o arquivo permanece salvo e o aviso informa a recarga pendente. Comandos usam o [IPC oficial](https://docs.noctalia.dev/noctalia/ipc/).
- **Diagnóstico:** resumo copiável com ambiente, disponibilidade dos serviços, output, workspace, IP e dependências. Não exporta configurações nem credenciais.

**Detecção de ambiente:** um binário instalado não habilita a integração. Hyprland precisa de sessão Wayland e IPC válido; Noctalia v5 e Vicinae precisam de processo do usuário no mesmo display/runtime e IPC funcionando. Noctalia legado v4 não habilita a edição TOML v5. A detecção é refeita em segundo plano a cada 30 segundos e pode ser solicitada manualmente. Os controles incompatíveis ficam desativados, e a proteção também existe nas ações do backend.

Em **GNOME**, o botão nativo abre `gnome-control-center display`; em **KDE Plasma**, abre `systemsettings kcm_kscreen`, somente no ambiente correspondente e se o programa estiver disponível. Sway, Niri e sessões desconhecidas são identificados para diagnóstico. **A criação/controle do monitor virtual continua implementada apenas para Hyprland**; não há backend virtual para GNOME, KDE, Sway ou Niri. Nestes ambientes, ligar, persistir regras Hyprland, editar o output e focar workspace do celular ficam indisponíveis. O editor de output aqui é o fluxo específico da aba Posição; os perfis de dispositivo podem ser consultados em qualquer ambiente.

## Comandos para launchers e atalhos

```bash
pipper --start          # liga o último perfil salvo/utilizado
pipper --stop           # encerra VNC e remove o output
pipper --toggle         # alterna ligado/desligado
pipper --focus          # foca o workspace configurado, padrão 11
pipper --status         # mostra conexão e estado
pipper --status --json  # mesmo estado em JSON
```

Os comandos de controle usam a mesma implementação da interface e um lock para evitar operações simultâneas. O último perfil é salvo ao ligar ou salvar no Hyprland, em `~/.config/pipper/device.json`, e permanece disponível depois de desligar. O CLI de controle não carrega GTK. A janela acompanha mudanças feitas por launcher/CLI em até cinco segundos. Um comando pode ser associado a uma tecla pelo Hyprland ou usado em um botão personalizado do Noctalia; o Pipper não altera automaticamente os atalhos pessoais.

## Configurações e preservação

- `src/devices.json`: predefinições. S22 padrão: `1920x1080@60`, posição `3552x1376`, escala `2.0`, workspace `11`; S22 Nativo: `2340x1080@60`, escala `3.6`.
- `src/config_manager.py`: validação, leitura, persistência, processos e integração com Hyprland/Noctalia.
- `src/main.py`: interface GTK4; comandos e I/O executados em uma fila de trabalho para manter a interface responsiva.
- `src/style.css`: tema Nord dedicado.
- `src/integrations.py`: detecção por sessão, comandos Noctalia, atalhos Vicinae e configurações nativas.
- `src/session.py`: operações compartilhadas e lock entre a interface e CLI.
- `src/cli.py`: comandos para terminal e launchers.

Na abertura, as regras literais em `~/.config/hypr/hyprland.lua`, seus includes locais `require()`/`dofile()` e os monitores de `hyprctl monitors all -j` são lidos. O estado em execução prevalece para resolução, atualização, posição e escala. O workspace escolhido vem da regra salva ou do registro da sessão ativa e é preservado ao reabrir, mesmo que o monitor esteja exibindo outro workspace. Includes cíclicos são limitados; Lua não é executada para descoberta, portanto regras geradas dinamicamente só podem ser descobertas quando o output está ativo. O arquivo `hyprland.conf` é lido e salvo em sintaxe legada quando não há `.lua`; o controle ao vivo requer a API Lua do compositor.

Regras do Hyprland são salvas em um único bloco `-- [PIPPER START]` / `-- [PIPPER END]`, ao final do arquivo. Noctalia usa `[bar.default.monitor.pipper]`, `[dock.monitor.pipper]`, `[notifications.monitor.pipper]`, `[osd.monitor.pipper]` e `[mpris.monitor.pipper]`, com `match` apontando ao output e `enabled = false` para ocultar. Regras existentes com outro nome e o mesmo `match` exato são reconhecidas e atualizadas junto com a regra Pipper. Wildcards são reconhecidos na leitura, mas preservados na edição por poderem afetar outras telas. A descoberta cobre o `config.toml` solicitado; outros arquivos TOML e overrides de estado do Noctalia podem prevalecer e precisam ser conciliados pelo usuário.

Antes de cada alteração, o arquivo original recebe um backup `<nome>.pipper-<timestamp>.bak` no mesmo diretório. Gravações são atômicas, preservam links simbólicos e permissões e rejeitam alterações concorrentes detectadas. TOML é validado e editado com `tomlkit` para preservar comentários. Marcadores incompletos não são sobrescritos. `XDG_CONFIG_HOME`, `XDG_STATE_HOME` e `NOCTALIA_CONFIG_HOME` são respeitados.

As escalas são verificadas por aritmética racional exata, sem tolerância de ponto flutuante. Valores já válidos são mantidos. Para correções, escolhe-se a escala válida mais próxima entre `0.25` e `10`, em passos de `0.01`; `2340x1080` com `3.5` vira `3.6`, resultando em `650x300` pixels lógicos.

O app usa a API atual `hl.dsp` para foco/movimentação do workspace e uma alternativa para versões Lua anteriores. Se o compositor ignorar o nome solicitado e criar `HEADLESS-N`, Pipper remove o output recém-criado e informa a incompatibilidade, evitando compartilhar uma tela diferente. A persistência salva regras, mas não liga automaticamente o VNC nem cria outputs no login. Logs de wayvnc ficam em `~/.local/state/pipper/wayvnc.log`.

## Verificação

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q src
# Fluxo da interface, isolado, se Xvfb estiver instalado:
xvfb-run -a env GDK_BACKEND=x11 GSK_RENDERER=cairo python3 tests/gtk_smoke.py
# Fechar e reabrir a janela com uma sessão ativa:
xvfb-run -a env GDK_BACKEND=x11 GSK_RENDERER=cairo python3 tests/gtk_lifecycle.py
# Habilitação de recursos em oito cenários de ambiente:
xvfb-run -a env GDK_BACKEND=x11 GSK_RENDERER=cairo python3 tests/gtk_environments.py
```

Os testes de configuração usam diretórios temporários; os de Hyprland simulam o compositor. Cobrem ajuste de escala de todos os perfis, entradas inválidas, backups, idempotência, includes, TOML, aliases, links simbólicos, criação/reutilização/sincronização, rollback e falhas do wayvnc. Os testes de editor verificam Hyprmon no Kitty, comandos com argumentos entre aspas, preferência persistida, dependências ausentes e limpeza após falha de abertura. O fluxo GTK verifica as abas, criação temporária para o editor e sincronização ao fechar. A conexão e interação por um cliente VNC precisam ser verificadas em uma sessão Hyprland e no celular real.

O teste de ciclo de vida GTK verifica que fechar preserva o VNC e o output ativo, que reabrir recupera um dispositivo personalizado sem regras salvas e que **Desligar Pipper** encerra a sessão. Também verifica o fechamento enquanto a tela está sendo ligada. Um teste com um processo real de espera, sem rede, confirma que o processo independente sobrevive ao encerramento do pai e pode ser encontrado e encerrado depois.

Os testes de integração verificam serviços instalados porém inativos, isolamento entre displays, Noctalia v4, proteção de ações em outros ambientes, perfis persistidos, toggle sem recriar servidor ativo e Script Commands válidos e idempotentes. Os fluxos gráficos e os ambientes usam serviços simulados; GNOME/KDE, Noctalia e Vicinae reais precisam ser conferidos nas respectivas sessões.

Referências de compatibilidade: [Monitores Hyprland](https://wiki.hypr.land/Configuring/Basics/Monitors/), [Dispatchers Lua](https://wiki.hypr.land/Configuring/Basics/Dispatchers/), [Configuração Noctalia v5](https://docs.noctalia.dev/noctalia/configuration/), [wayvnc](https://github.com/any1/wayvnc).

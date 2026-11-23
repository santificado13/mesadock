# Changelog

Todas as mudanças relevantes do MesaDock. Formato inspirado em
[Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versões seguem
[SemVer](https://semver.org/lang/pt-BR/).

## [Não lançado]

### Adicionado
- **Dock de pasta:** uma dock que mostra o conteúdo de uma pasta ao vivo
  ("+ Dock de pasta" no Gerenciador ou "Nova dock de pasta..." na bandeja).
  Só lê a pasta, nunca a altera; se a pasta ficar indisponível, os itens e os
  ícones personalizados são mantidos.
- **Busca rápida** (Ctrl+Alt+B): acha e abre qualquer item de qualquer
  dock digitando parte do nome, sem diferenciar acentos ou maiúsculas.
- **Trazer para a frente** (Ctrl+Alt+F): mostra as docks por cima das janelas.
- **Ocultar docks** (Ctrl+Alt+H ou duplo clique no papel de parede; o duplo
  clique pode ser desligado nas Configurações).
- Ícone personalizado por item: "Trocar ícone..." no clique direito do item no
  painel e botão "Ícone..." no Gerenciador (PNG, ICO, JPG, BMP ou EXE). A imagem
  é copiada para a pasta do MesaDock; "Voltar ao ícone original" desfaz.
- CI no GitHub Actions: lint (ruff) e testes no Windows com Python 3.12 e 3.14
  a cada envio; em tags `v*` o exe é gerado e anexado como artefato.

- O log registra como o MesaDock foi fechado: "Quit requested: <origem>"
  (menu da bandeja, botão do Gerenciador, janela principal), fim de sessão do
  Windows, "MesaDock exited normally" e "Process exiting" ao final. Um log que
  termina sem essas linhas indica que o processo foi encerrado de fora.

### Corrigido
- Atalhos de apps da web do Chrome/Edge (e outros com ícone próprio) perdiam o
  desenho ao entrar na dock: o ícone era lido do `chrome_proxy.exe`. Agora vale
  o ícone indicado no próprio atalho, e arquivos `.ico` são lidos no tamanho máximo.
- Links web mostram o ícone do navegador padrão em vez do desenho da dock.
- O log crescia sem limite: agora gira em 1 MB e guarda só 3 cópias (no
  máximo ~4 MB). Eventos de passagem do mouse só entram com `MESADOCK_DEBUG=1`.
- Imports e variáveis sem uso apontados pelo ruff.

## [1.1.0] - 2026-11-20

### Adicionado
- Visual novo: tema escuro coeso, Gerenciador reorganizado, ícones das docks em
  vidro com a cor de cada dock e contador de itens, painéis mais limpos.
- Nome da dock sobre uma pílula escura, legível em qualquer papel de parede.
- Ctrl+Shift+M abre o Gerenciador de qualquer lugar do Windows.
- Escolha de idioma (PT | EN) salva nas configurações.
- Persistência em SQLite.
- `tests/test_i18n.py`: falha se algum texto passado a `tr()` não tiver tradução.

### Alterado
- Modo de arquivo padrão agora é "copy": o atalho original fica na área de trabalho.
- `build.ps1` gera o exe num ambiente isolado (27 MB em vez de 48 MB), empacota só
  os assets versionados, falha de verdade quando não consegue substituir o exe e
  gera `dist\MesaDock-<versão>.zip`.

### Corrigido
- Menus da dock, da bandeja, confirmações e mensagens que apareciam em inglês.
- Contador da dock aparecia como um ponto sem número.
- Vazamento de referência COM ao extrair ícones grandes.
- Caminho pessoal fixo no código de início automático.
- Bordas claras em abas e listas no tema escuro; textos cortados nas Configurações.

## [1.0.0]

- Primeira versão pública.

[Não lançado]: https://github.com/santificado13/mesadock/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/santificado13/mesadock/compare/v1.0.0...v1.1.0

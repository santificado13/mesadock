"""Minimal PT/EN translations for the Manager UI.

The source strings are English. When the user's Windows display language is
Portuguese, tr() returns the Portuguese equivalent; otherwise it returns the
English text unchanged (so English stays the safe default and never breaks).
"""
from __future__ import annotations

import ctypes

_PT = {
    "Manager": "Gerenciador",
    "Profile": "Perfil",
    "New profile": "Novo perfil",
    "DOCKS": "DOCKS",
    "Docks": "Docks",
    "+ New dock": "+ Novo dock",
    "Dock": "Dock",
    "Settings": "Configurações",
    "About": "Sobre",
    "Language": "Idioma",
    "Expand style": "Estilo de expansão",
    "Grid": "Grade",
    "Column": "Coluna",
    "Row": "Linha",
    "Fan": "Leque",
    "Ring": "Anel",
    "Add shortcuts...": "Adicionar atalhos...",
    "Add web link...": "Link web",
    "Add desktop shortcuts": "Da área de trabalho",
    "Delete dock": "Excluir dock",
    "Item": "Item",
    "Type": "Tipo",
    "Target": "Alvo",
    "Open": "Abrir",
    "Move up": "Mover acima",
    "Move down": "Mover abaixo",
    "Remove": "Remover",
    "Hover delay (ms)": "Atraso do hover (ms)",
    "Panel theme": "Tema do painel",
    "Show item names under icons": "Mostrar nomes sob os ícones",
    "Snap docks to the desktop icon grid": "Encaixar docks na grade do desktop",
    "Animate panels": "Animar painéis",
    "Start MesaDock when I sign in": "Iniciar o MesaDock ao entrar",
    "Start minimised (docks only)": "Iniciar minimizado (só docks)",
    "Keep docks behind normal windows (desktop layer)": "Manter docks atrás das janelas (camada do desktop)",
    "Data folder": "Pasta de dados",
    "Open data folder": "Abrir pasta de dados",
    "Restore all archived shortcuts": "Restaurar todos os atalhos arquivados",
    "Quit MesaDock": "Sair do MesaDock",
    "Ready": "Pronto",
    "Every shortcut group, one desktop icon.": "Cada grupo de atalhos, um ícone no desktop.",
    "Open Manager": "Abrir Gerenciador",
    "New dock": "Novo dock",
    "No docks yet.\nClick + New dock to start.": "Nenhum dock ainda.\nClique em + Novo dock para começar.",
    "Choose a dock icon": "Escolha um ícone para o dock",
    "Add shortcuts and files": "Adicionar atalhos e arquivos",
    "No shortcuts found on the desktop": "Nenhum atalho encontrado no desktop",
    "Cancelled. Nothing was moved.": "Cancelado. Nada foi movido.",
    "Item removed; original restored if it was archived": "Item removido; original restaurado se foi arquivado",
    "Dock deleted": "Dock excluído",
    "Renamed to ": "Renomeado para ",
    "Style set to ": "Estilo definido para ",
    "Icon updated": "Ícone atualizado",
    "Dock creation cancelled.": "Criação do dock cancelada.",
    "Switched to profile ": "Mudou para o perfil ",
    "Could not open ": "Não foi possível abrir ",
    "Restored ": "Restaurados ",
    " archived item(s)": " item(ns) arquivado(s)",
    "App": "App",
    "Web": "Web",
    "Folder": "Pasta",
    "Script": "Script",
    "File": "Arquivo",
    "item": "item",
    "items": "itens",
    "shortcut": "atalho",
    "shortcuts": "atalhos",
    "Delete": "Excluir",
    "Name this dock:": "Nome deste dock:",
    "Address (https://...)": "Endereço (https://...)",
    "Profile name": "Nome do perfil",
    "1 shortcut": "1 atalho",
    " shortcuts": " atalhos",
    "Empty dock": "Dock vazio",
    "Opening": "Abertura",
    "Open on hover": "Abrir ao passar o mouse",
    "Open on click": "Abrir ao clicar",
    "Panel look": "Aparência do painel",
    "Translucent": "Translúcido",
    "Solid": "Sólido",
    "Opacity": "Opacidade",
    "Icon size": "Tamanho do ícone",
    "Desktop": "Área de trabalho",
    "Move originals into the archive": "Mover os originais para o arquivo",
    "Keep originals where they are": "Manter os originais onde estão",
    "On: docks stay above the wallpaper but behind apps.\nOff: docks float above every window.":
        "Ligado: as docks ficam sobre o papel de parede, mas atrás dos apps.\n"
        "Desligado: as docks flutuam sobre todas as janelas.",
    "Could not save: ": "Não foi possível salvar: ",
    " item added": " item adicionado",
    " items added": " itens adicionados",
    "Nothing could be added": "Nada pôde ser adicionado",
    "Could not add link": "Não foi possível adicionar o link",
    "Style: ": "Estilo: ",
    "Remove dock (restores items)": "Excluir dock (devolve os itens)",
    "Remove dock": "Excluir dock",
    "Remove \"{name}\"?\n\nItems are put back on the desktop.": "Excluir \"{name}\"?\n\nOs itens voltam para a área de trabalho.",
    "Add web link": "Adicionar link web",
    "Address:": "Endereço:",
    "Remove from dock (puts it back on the desktop)": "Remover da dock (volta para a área de trabalho)",
    "Remove from dock (leaves the original alone)": "Remover da dock (mantém o original)",
    "Manage this dock...": "Gerenciar esta dock...",
    "The shortcut goes back to the desktop.": "O atalho volta para a área de trabalho.",
    "The shortcut itself is not touched, it just leaves the dock.": "O atalho original não é alterado, só sai da dock.",
    "Remove from dock": "Remover da dock",
    "Remove \"{item}\" from {dock}?": "Remover \"{item}\" de {dock}?",
    "Empty url": "Endereço vazio",
    "Could not store link: ": "Não foi possível salvar o link: ",
    "Link added": "Link adicionado",
    "Added": "Adicionado",
    "Empty path": "Caminho vazio",
    "Not found: ": "Não encontrado: ",
    "Folder linked in place": "Pasta vinculada no lugar",
    "Could not add: ": "Não foi possível adicionar: ",
    "Dock \"{name}\" created.": "Dock \"{name}\" criada.",
    "Shortcuts": "Atalhos",
    "All files": "Todos os arquivos",
    "Add {count} desktop shortcut(s) to \"{name}\"?": "Adicionar {count} atalho(s) da área de trabalho a \"{name}\"?",
    "Profile {name} created": "Perfil {name} criado",
    "MesaDock Manager": "MesaDock — Gerenciador",
    "Restored {count} archived item(s)": "{count} item(ns) arquivado(s) restaurado(s)",
    "MesaDock stopped unexpectedly.\n\nSee ": "O MesaDock parou inesperadamente.\n\nVeja ",
    "Choose a PNG, ICO, JPG, BMP or EXE file": "Escolha um arquivo PNG, ICO, JPG, BMP ou EXE",
    "Choose an icon": "Escolher ícone",
    "Images and programs": "Imagens e programas",
    "Change icon...": "Trocar ícone...",
    "Use the original icon": "Voltar ao ícone original",
    "Icon...": "Ícone...",
    "Select an item first": "Selecione um item primeiro",
    "Choose the folder this dock will show": "Escolha a pasta que esta dock vai mostrar",
    "This dock shows a folder. Put the file in the folder itself.":
        "Esta dock mostra uma pasta. Coloque o arquivo na própria pasta.",
    "This dock shows a folder. Remove the file from the folder itself.":
        "Esta dock mostra uma pasta. Remova o arquivo da própria pasta.",
    "Open folder": "Abrir pasta",
    "Change folder...": "Trocar pasta...",
    "Show in folder": "Mostrar na pasta",
    "+ Folder dock": "+ Dock de pasta",
    "shows the folder ": "mostra a pasta ",
    "Double-click the desktop to hide or show the docks":
        "Duplo clique na área de trabalho oculta ou mostra as docks",
    "Nothing found": "Nada encontrado",
    "Enter opens  ·  ↑ ↓ choose  ·  Esc closes": "Enter abre  ·  ↑ ↓ escolhe  ·  Esc fecha",
    "Type to find a shortcut in any dock": "Digite para achar um atalho em qualquer dock",
    "Search shortcuts...": "Buscar atalhos...",
    "New folder dock...": "Nova dock de pasta...",
    "Send docks behind windows": "Mandar as docks para trás das janelas",
    "Bring docks to the front": "Trazer as docks para a frente",
    "Show docks": "Mostrar docks",
    "Hide docks": "Ocultar docks",
    "Remove \"{name}\"?\n\nThe folder and its files are not touched.":
        "Excluir \"{name}\"?\n\nA pasta e os arquivos dela não são alterados.",
    "A folder dock follows the order of its folder": "A dock de pasta segue a ordem da própria pasta",
    "Colour": "Cor",
    "Size": "Tamanho",
    "Small": "Pequeno",
    "Medium": "Médio",
    "Large": "Grande",
    "Tint the icons": "Tingir os ícones",
    "New tab...": "Nova aba...",
    "No tab": "Sem aba",
    "Move to tab": "Mover para a aba",
    "Tab name (leave empty for none):": "Nome da aba (deixe vazio para nenhuma):",
    "Existing tabs: ": "Abas existentes: ",
    "Tab": "Aba",
    "Could not create the backup: ": "Não foi possível criar o backup: ",
    "Backup saved: ": "Backup salvo: ",
    "Could not restore the backup: ": "Não foi possível restaurar o backup: ",
    "Backup restored": "Backup restaurado",
    "Save the backup as": "Salvar o backup como",
    "MesaDock backup": "Backup do MesaDock",
    "Choose the backup to restore": "Escolha o backup para restaurar",
    "Restore a backup...": "Restaurar um backup...",
    "Replace the current docks, shortcuts and settings with this backup?\n\nWhat you have now is kept in the data folder, under backups.": "Substituir as docks, os atalhos e as configurações atuais por este backup?\n\nO que você tem agora fica guardado na pasta de dados, em backups.",
    "Rules": "Regras",
    "new desktop items. E.g. *.pdf, report*": "itens novos da área de trabalho. Ex.: *.pdf, relatorio*",
    "Tab...": "Aba...",
    "Rules saved": "Regras salvas",
    "Rules removed": "Regras removidas",
    "Back up...": "Fazer backup...",
    "A backup holds every profile, dock, shortcut and setting. One is also made\nautomatically each day and the last 7 are kept in the data folder.": "O backup guarda todos os perfis, docks, atalhos e configurações. Um também é feito\nautomaticamente a cada dia, e os 7 últimos ficam na pasta de dados.",
    "All": "Todos",
    "Next profile": "Próximo perfil",
}


def _is_portuguese() -> bool:
    try:
        lang = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return lang in (0x0416, 0x0816)  # pt-BR, pt-PT
    except Exception:
        return False


_LANG = "pt" if _is_portuguese() else "en"


def set_lang(lang: str) -> None:
    """Set the UI language: 'pt' or 'en'."""
    global _LANG
    _LANG = "pt" if lang == "pt" else "en"


def get_lang() -> str:
    """Return the current UI language: 'pt' or 'en'."""
    return _LANG


def tr(text: str) -> str:
    """Translate text to Portuguese when the UI language is Portuguese."""
    if _LANG != "pt":
        return text
    return _PT.get(text, text)

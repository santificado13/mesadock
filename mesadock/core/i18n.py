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

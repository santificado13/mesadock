"""Capture the real UI for the documentation screenshots.

Usage:  python tools/capture_screens.py [--lang pt|en] [--home DIR] [--out DIR]

The script builds a throw-away profile with sample docks (system executables,
web links and a sample folder it creates itself - it never touches your desktop
or your data), puts a generated wallpaper behind everything so nothing else on
the screen ends up in a picture, opens each panel, the quick search and the
Manager, and writes PNGs. Docks and panels are layered windows, so they are
grabbed with their real transparency over that wallpaper.

Default output: docs/screens/<lang>/
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFilter, ImageGrab, ImageTk  # noqa: E402

from mesadock.core import i18n  # noqa: E402
from mesadock.core.models import DockFolder, DockItem  # noqa: E402
from mesadock.core.store import Store  # noqa: E402
from mesadock.win32 import dpi  # noqa: E402

TEXT = {
    "pt": {"work": "Trabalho", "media": "Mídia", "tools": "Ferramentas", "daily": "Diário", "docs": "Documentos",
           "office": "Escritório", "system": "Sistema", "explorer": "Explorador", "notepad": "Bloco de Notas",
           "calc": "Calculadora", "terminal": "Terminal", "charmap": "Caracteres", "remote": "Área Remota",
           "settings": "Configurações", "powershell": "PowerShell", "devices": "Dispositivos", "cleanup": "Limpeza",
           "registry": "Registro", "services": "Eventos", "sysinfo": "Sistema", "mail": "E-mail", "calendar": "Agenda", "notes": "Notas",
           "files": ("Relatório anual.pdf", "Orçamento.xlsx", "Ata da reunião.docx", "Contratos"),
           "query": "calc"},
    "en": {"work": "Work", "media": "Media", "tools": "Tools", "daily": "Daily", "docs": "Documents",
           "office": "Office", "system": "System", "explorer": "Explorer", "notepad": "Notepad",
           "calc": "Calculator", "terminal": "Terminal", "charmap": "Characters", "remote": "Remote Desktop",
           "settings": "Settings", "powershell": "PowerShell", "devices": "Devices", "cleanup": "Cleanup",
           "registry": "Registry", "services": "Events", "sysinfo": "System Info", "mail": "Mail", "calendar": "Calendar", "notes": "Notes",
           "files": ("Annual report.pdf", "Budget.xlsx", "Meeting notes.docx", "Contracts"),
           "query": "calc"},
}


def exe(*parts: str) -> str:
    return os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", *parts)


def windir(name: str) -> str:
    return os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), name)


def sample_folder(words: dict) -> Path:
    folder = Path(tempfile.gettempdir()) / ("mesadock-sample-" + words["docs"])
    folder.mkdir(parents=True, exist_ok=True)
    *files, subfolder = words["files"]
    for name in files:
        (folder / name).write_bytes(b"sample")
    (folder / subfolder).mkdir(exist_ok=True)
    return folder


def build_store(words: dict, origin: tuple[int, int]) -> Store:
    left, top = origin
    store = Store()
    store.settings.show_labels = True
    store.settings.icon_size = 64
    store.settings.animations = False
    store.settings.panel_opacity = 0.86
    # Screenshots need the windows above the wallpaper window; the shipped
    # default keeps docks and panels on the desktop layer.
    store.settings.attach_to_desktop = False
    store.settings.language = "pt" if words is TEXT["pt"] else "en"

    work = DockFolder(name=words["work"], style="grid", position=(left + 230, top + 600))
    for key, target, tab in (("explorer", windir("explorer.exe"), "office"), ("notepad", windir("notepad.exe"), "office"),
                             ("calc", exe("calc.exe"), "office"), ("charmap", exe("charmap.exe"), "office"),
                             ("terminal", exe("cmd.exe"), "system"), ("remote", exe("mstsc.exe"), "system"),
                             ("settings", exe("control.exe"), "system"),
                             ("powershell", exe("WindowsPowerShell", "v1.0", "powershell.exe"), "system")):
        work.add_item(DockItem(name=words[key], kind="shortcut", path=target, target=target, tab=words[tab]))
    work.tabs = [words["office"], words["system"]]

    media = DockFolder(name=words["media"], style="fan", accent="amber", position=(left + 450, top + 600))
    for label in ("Spotify", "YouTube", "Netflix", "Twitch"):
        media.add_item(DockItem(name=label, kind="url", target="https://" + label.lower() + ".com"))

    tools = DockFolder(name=words["tools"], style="ring", accent="rose", position=(left + 670, top + 600))
    for key, target in (("devices", exe("devmgmt.msc")), ("cleanup", exe("cleanmgr.exe")),
                        ("registry", windir("regedit.exe")), ("services", exe("eventvwr.exe")),
                        ("sysinfo", exe("msinfo32.exe"))):
        tools.add_item(DockItem(name=words[key], kind="shortcut", target=target))

    daily = DockFolder(name=words["daily"], style="column", accent="teal", tint=True, position=(left + 890, top + 600))
    for key in ("mail", "calendar", "notes"):
        daily.add_item(DockItem(name=words[key], kind="url", target="https://example.com/" + key))

    docs = DockFolder(name=words["docs"], style="grid", position=(left + 1110, top + 600),
                      portal=str(sample_folder(words)))
    store.profiles[0].folders = [work, media, tools, daily, docs]
    store.save()
    return store


def wallpaper(size: tuple[int, int]) -> Image.Image:
    """A calm generated wallpaper: a dark blue-violet gradient with soft light."""
    width, height = size
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        t = y / max(1, height - 1)
        draw.line([(0, y), (width, y)], fill=(int(24 + 40 * t), int(40 + 18 * t), int(92 + 26 * t)))
    glow = Image.new("RGB", (width, height), (0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    for (cx, cy, radius, colour) in ((0.2, 0.25, 0.32, (120, 90, 210)), (0.82, 0.7, 0.38, (40, 150, 190)),
                                     (0.55, 1.05, 0.45, (210, 90, 150))):
        r = radius * width
        glow_draw.ellipse([cx * width - r, cy * height - r, cx * width + r, cy * height + r], fill=colour)
    glow = glow.filter(ImageFilter.GaussianBlur(width * 0.08))
    return Image.blend(image, glow, 0.35)


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture MesaDock screenshots")
    parser.add_argument("--lang", choices=sorted(TEXT), default="pt")
    parser.add_argument("--home", default=None, help="data folder (default: a new temporary one)")
    parser.add_argument("--out", default=None, help="output folder (default: docs/screens/<lang>)")
    args = parser.parse_args()

    os.environ["MESADOCK_HOME"] = args.home or tempfile.mkdtemp(prefix="mesadock-shots-")
    os.environ["MESADOCK_NO_DESKTOP"] = "1"
    out = Path(args.out) if args.out else ROOT / "docs" / "screens" / args.lang
    out.mkdir(parents=True, exist_ok=True)
    dpi.enable_per_monitor_v2()
    words = TEXT[args.lang]
    i18n.set_lang(args.lang)

    from mesadock.ui.app import MesaDockApp

    # The stage: a wallpaper window covering the part of the screen we use.
    probe = tk.Tk()
    probe.withdraw()
    screen_w, screen_h = probe.winfo_screenwidth(), probe.winfo_screenheight()
    probe.destroy()
    stage_w, stage_h = min(1400, screen_w - 40), min(900, screen_h - 80)
    origin = (20, 20)

    store = build_store(words, origin)
    app = MesaDockApp(store=store)
    app.background_watch = False
    i18n.set_lang(args.lang)
    stage = tk.Toplevel(app.root)
    stage.overrideredirect(True)
    stage.geometry("%dx%d+%d+%d" % (stage_w, stage_h, origin[0], origin[1]))
    backdrop = ImageTk.PhotoImage(wallpaper((stage_w, stage_h)))
    tk.Label(stage, image=backdrop, bd=0).pack()
    stage.attributes("-topmost", True)
    app.start(minimized=True)
    app.start_portal_watcher()
    app.pin_panels(True)

    def pump(seconds: float = 0.5) -> None:
        end = time.time() + seconds
        while time.time() < end:
            app.root.update()
            time.sleep(0.02)

    def front(*windows) -> None:
        for window in windows:
            window.attributes("-topmost", True)
            window.lift()

    def grab(name: str, box: tuple[int, int, int, int], pad: int = 14) -> None:
        left, top, right, bottom = box
        area = (max(origin[0], left - pad), max(origin[1], top - pad),
                min(origin[0] + stage_w, right + pad), min(origin[1] + stage_h, bottom + pad))
        image = ImageGrab.grab(area, all_screens=True, include_layered_windows=True).convert("RGB")
        image.save(out / name)
        print("SHOT", name, image.size)

    def union(*boxes) -> tuple[int, int, int, int]:
        return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))

    def dock_box(folder) -> tuple[int, int, int, int]:
        x, y, w, h = app.docks[folder.id].rect()
        return (x, y, x + w, y + h)

    def panel_box(folder) -> tuple[int, int, int, int]:
        panel = app.panels[folder.id]
        x, y = panel._window_origin()
        w, h = panel._window_size()
        return (x, y, x + w, y + h)

    from mesadock.core import portal as portal_mod

    docs = store.folders[4]
    portal_mod.sync_items(docs)
    pump(1.2)
    front(stage)
    for folder in store.folders:
        front(app.docks[folder.id].window)
    pump(0.6)
    grab("desktop.png", union(*(dock_box(f) for f in store.folders)), pad=40)

    work, media, tools, daily, docs = store.folders
    for folder, name, hover in ((work, "panel-tabs.png", 2), (media, "panel-fan.png", 1),
                                (tools, "panel-ring.png", 1), (daily, "panel-column.png", -1),
                                (docs, "panel-folder.png", 0)):
        app.open_panel(folder)
        pump(0.6)
        panel = app.panels[folder.id]
        front(panel.window)
        if hover >= 0:
            panel._set_hover(hover)
        pump(0.35)
        grab(name, union(panel_box(folder), dock_box(folder)))
        app.close_all_panels()
        pump(0.3)

    work.active_tab = work.tabs[1]
    app.open_panel(work)
    pump(0.6)
    front(app.panels[work.id].window)
    pump(0.3)
    grab("panel-tabs-system.png", union(panel_box(work), dock_box(work)))
    app.close_all_panels()
    work.active_tab = ""
    pump(0.3)

    # The search opens on the monitor under the mouse, which may be another
    # one; for the picture it has to open on the primary, where the stage is.
    under_mouse = app.monitor_for
    app.monitor_for = lambda _point: app.primary_monitor()
    app.open_search()
    app.monitor_for = under_mouse
    pump(0.4)
    app.search.query.set(words["query"])
    front(app.search.window)
    pump(0.5)
    window = app.search.window
    window.update_idletasks()
    x, y = window.winfo_rootx(), window.winfo_rooty()
    grab("search.png", (x, y, x + window.winfo_width(), y + window.winfo_height()), pad=24)
    app.search.close()
    pump(0.3)

    app.open_manager(select=work.id)
    pump(1.0)
    manager = app.manager.window
    manager.geometry("1040x700+%d+%d" % (origin[0] + 60, origin[1] + 40))
    front(manager)
    pump(0.9)
    box = (manager.winfo_rootx(), manager.winfo_rooty(),
           manager.winfo_rootx() + manager.winfo_width(), manager.winfo_rooty() + manager.winfo_height())
    grab("manager-dock.png", box, pad=0)
    app.manager.show_tab("settings")
    pump(0.7)
    grab("manager-settings.png", box, pad=0)
    app.manager.show_tab("about")
    pump(0.4)
    # The throw-away data folder lives under the user's profile, so its path would
    # print the account name in a public picture: show the usual location.
    real_home = str(Path(os.environ["MESADOCK_HOME"]))

    def neutral(widget) -> None:
        for child in widget.winfo_children():
            try:
                if child.cget("text") == real_home:
                    child.configure(text=r"%APPDATA%\MesaDock")
            except tk.TclError:
                pass
            neutral(child)

    neutral(manager)
    pump(0.4)
    grab("manager-about.png", box, pad=0)
    app.quit()  # also destroys the wallpaper window, a child of the app's root
    print("screenshots written to", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Capture the real UI for the documentation screenshots.

Usage:  python tools/capture_screens.py [--home DIR] [--out DIR]

The script builds a throw-away profile with sample docks (system executables and
links only - it never moves a file from your desktop), opens each panel and the
Manager, and writes PNGs through mesadock.ui.capture so DPI scaling behaves the
same way the app does.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mesadock.core.models import DockFolder, DockItem  # noqa: E402
from mesadock.core.store import Store  # noqa: E402
from mesadock.ui import capture  # noqa: E402
from mesadock.win32 import dpi  # noqa: E402


def build_store() -> Store:
    system = os.environ.get("SystemRoot", r"C:\Windows")

    def exe(*parts: str) -> str:
        return os.path.join(system, "System32", *parts)

    store = Store()
    store.settings.show_labels = True
    store.settings.icon_size = 72
    store.settings.animations = False
    store.settings.panel_opacity = 1.0
    # Screenshots need the windows above other apps; the shipped default keeps
    # docks and panels on the desktop layer.
    store.settings.attach_to_desktop = False

    work = DockFolder(name="Work", style="grid", position=(80, 220))
    for label, target in [
        ("Explorer", exe("explorer.exe")),
        ("Notepad", exe("notepad.exe")),
        ("Calculator", exe("calc.exe")),
        ("Terminal", exe("cmd.exe")),
        ("Paint", exe("mspaint.exe")),
        ("Snipping Tool", exe("SnippingTool.exe")),
        ("Task Manager", exe("Taskmgr.exe")),
        ("Settings", exe("control.exe")),
        ("PowerShell", exe("WindowsPowerShell", "v1.0", "powershell.exe")),
    ]:
        work.add_item(DockItem(name=label, kind="shortcut", path=target, target=target))

    media = DockFolder(name="Media", style="fan", position=(80, 420))
    for label in ("Spotify", "YouTube", "Netflix", "Twitch"):
        media.add_item(DockItem(name=label, kind="url", target="https://" + label.lower() + ".com"))

    ring = DockFolder(name="Tools", style="ring", position=(80, 620))
    for label in ("Devices", "Cleanup", "Registry", "Services"):
        ring.add_item(DockItem(name=label, kind="shortcut", target=exe("cmd.exe")))

    column = DockFolder(name="Daily", style="column", position=(230, 220))
    for label in ("Mail", "Calendar", "Notes"):
        column.add_item(DockItem(name=label, kind="url", target="https://example.com/" + label.lower()))

    store.profiles[0].folders = [work, media, ring, column]
    store.save()
    return store


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture MesaDock screenshots")
    parser.add_argument("--home", default=str(ROOT / "_demohome"))
    parser.add_argument("--out", default=str(ROOT / "docs" / "screens"))
    args = parser.parse_args()

    os.environ["MESADOCK_HOME"] = args.home
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    dpi.enable_per_monitor_v2()

    from mesadock.ui.app import MesaDockApp

    store = build_store()
    app = MesaDockApp(store=store)
    app.start(minimized=True)
    app.pin_panels(True)

    def pump(seconds: float = 0.5) -> None:
        end = time.time() + seconds
        while time.time() < end:
            app.root.update()
            time.sleep(0.02)

    def shot(name: str, window, pad: int = 6) -> None:
        image = capture.grab_window(window, out / name, pad=pad)
        print("SHOT", name, image.size, capture.colour_stats(image, 3))

    pump(1.2)
    for folder in store.folders:
        dock = app.docks[folder.id]
        dock.window.attributes("-topmost", True)
        dock.window.lift()
    pump(0.6)
    shot("dock-grid.png", app.docks[store.folders[0].id].window)
    shot("dock-fan.png", app.docks[store.folders[1].id].window)
    shot("dock-ring.png", app.docks[store.folders[2].id].window)
    for folder in store.folders:
        app.docks[folder.id].window.attributes("-topmost", False)

    for folder, name in (
        (store.folders[0], "panel-grid.png"),
        (store.folders[1], "panel-fan.png"),
        (store.folders[2], "panel-ring.png"),
        (store.folders[3], "panel-column.png"),
    ):
        app.open_panel(folder)
        pump(0.7)
        panel = app.panels[folder.id]
        panel.window.lift()
        pump(0.25)
        shot(name, panel.window, pad=8)
        app.close_panels()
        pump(0.25)

    app.open_manager()
    pump(1.0)
    app.manager.window.geometry("1040x700+380+140")
    app.manager.window.lift()
    app.manager.window.attributes("-topmost", True)
    pump(0.9)
    shot("manager-dock.png", app.manager.window, pad=0)
    app.manager.show_tab("settings")
    pump(0.7)
    shot("manager-settings.png", app.manager.window, pad=0)
    app.manager.show_tab("about")
    pump(0.7)
    shot("manager-about.png", app.manager.window, pad=0)
    app.manager.show_tab("dock")
    pump(0.4)
    app.quit()
    print("screenshots written to", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

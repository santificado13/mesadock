"""Static consistency check: every self.app.X used by the UI exists on MesaDockApp.

Instance attributes assigned in __init__ count as existing, so only methods that
are genuinely missing are reported. Run: python tools/lint_refs.py
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mesadock.ui.app import MesaDockApp
from mesadock.ui.dockwindow import DockWindow
from mesadock.ui.manager import ManagerWindow
from mesadock.ui.panel import Panel
from mesadock.ui.tray import TrayIcon

OWNERS = {"manager.py": ManagerWindow, "panel.py": Panel,
          "dockwindow.py": DockWindow, "tray.py": TrayIcon}


def class_members(cls) -> set:
    names = set(dir(cls))
    try:
        with open(sys.modules[cls.__module__].__file__, encoding="utf-8") as handle:
            source = ast.parse(handle.read())
    except Exception:
        return names
    for node in ast.walk(source):
        if isinstance(node, ast.ClassDef) and node.name == cls.__name__:
            for item in ast.walk(node):
                if (isinstance(item, ast.Attribute) and isinstance(item.value, ast.Name)
                        and item.value.id == "self" and isinstance(item.ctx, ast.Store)):
                    names.add(item.attr)
    return names


APP_MEMBERS = class_members(MesaDockApp)
bad, checked = [], 0
for folder, _dirs, files in os.walk(os.path.join(ROOT, "mesadock")):
    for name in files:
        if not name.endswith(".py"):
            continue
        path = os.path.join(folder, name)
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), path)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute)):
                continue
            inner = node.value
            if not (isinstance(inner.value, ast.Name) and inner.value.id == "self"
                    and inner.attr == "app"):
                continue
            checked += 1
            if node.attr in APP_MEMBERS:
                continue
            owner = OWNERS.get(name)
            if owner is not None and node.attr in class_members(owner):
                continue
            bad.append((os.path.relpath(path, ROOT), node.lineno, node.attr))

print("self.app references checked:", checked)
print("MISSING:", sorted(set(bad)) if bad else "none")

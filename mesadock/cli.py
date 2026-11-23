"""Command line tools: doctor, list, add, restore, autostart, export and import.

These commands never start the GUI, which makes them safe in scripts, in the
installer's post-install step, and in tests.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path

from .core import archive as archive_mod
from .core import paths
from .core.models import DockFolder
from .core.store import Store
from .win32 import desktop, dpi, monitors, shell


def _load() -> Store:
    paths.ensure_dirs()
    return Store(paths.store_file()).load()


def _version() -> str:
    from . import __version__

    return __version__


def cmd_doctor(args: argparse.Namespace) -> int:
    """Report everything MesaDock depends on, without changing anything."""
    store = _load()
    info: dict[str, object] = {}
    info["version"] = _version()
    info["python"] = sys.version.split()[0]
    info["windows"] = shell.is_windows()
    info["platform"] = sys.platform
    info["tk"] = _tk_version()
    info["dpi_mode"] = dpi.enable_per_monitor_v2()
    try:
        info["monitors"] = [
            {"rect": list(m.rect), "work": list(m.work), "scale": round(m.scale, 2), "primary": m.primary}
            for m in monitors.list_monitors()
        ]
    except Exception as exc:  # pragma: no cover - hardware specific
        info["monitors"] = "error: " + str(exc)
    info["desktop_window"] = desktop.desktop_window()
    info["icon_count"] = desktop.icon_count()
    info["icon_spacing"] = list(desktop.icon_spacing())
    info["home"] = str(paths.home_dir())
    info["store"] = str(paths.store_file())
    info["store_exists"] = paths.store_file().exists()
    info["store_error"] = store.last_error
    info["profiles"] = [p.name for p in store.profiles]
    info["active_profile"] = store.active_profile.name
    info["docks"] = len(store.folders)
    info["items"] = sum(len(f.items) for f in store.folders)
    info["archived"] = _count_archived()
    info["autostart"] = shell.autostart_enabled()
    if args.json:
        print(json.dumps(info, indent=2, ensure_ascii=False))
        return 0
    print("MesaDock " + str(info["version"]) + " - environment check\n")
    labels = {
        "version": "version",
        "python": "python",
        "windows": "windows",
        "platform": "platform",
        "tk": "tk",
        "dpi_mode": "DPI mode",
        "monitors": "monitors",
        "desktop_window": "desktop window",
        "icon_count": "desktop icons",
        "icon_spacing": "icon spacing",
        "home": "data folder",
        "store": "store file",
        "store_exists": "store exists",
        "store_error": "store error",
        "profiles": "profiles",
        "active_profile": "active profile",
        "docks": "docks",
        "items": "items",
        "archived": "archived files",
        "autostart": "start with Windows",
    }
    for key, value in info.items():
        print(str(labels.get(key, key)).ljust(18) + str(value))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    store = _load()
    print("profile: " + store.active_profile.name + "  (" + str(len(store.profiles)) + " total)")
    if not store.folders:
        print("no docks yet - run: mesadock add <dock> <path>")
        return 0
    for folder in store.folders:
        print(folder.name + "  [" + folder.style + "]  " + str(len(folder.items)) + " item(s)  id=" + folder.id)
        for item in folder.items:
            print("    - " + item.name + "  (" + item.kind + ")  " + (item.target or item.path))
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    store = _load()
    folder = store.folder_by_id(args.dock) if args.dock else None
    if folder is None and args.dock:
        folder = next((f for f in store.folders if f.name.lower() == args.dock.lower()), None)
    if folder is None:
        folder = DockFolder(name=args.dock or "New dock", style=args.style)
        store.add_folder(folder)
        print("created dock " + folder.name)

    archiver = archive_mod.Archiver(store.active_profile.name, store.settings.archive_mode)
    added = 0
    for source in args.paths:
        if shell.is_url(source):
            result = archiver.add_url(source, folder.id)
        else:
            result = archiver.add_from_path(source, folder.id)
        if result.ok and result.item is not None:
            folder.add_item(result.item)
            added += 1
            print("added " + result.item.name)
        else:
            print("skipped " + source + ": " + result.message, file=sys.stderr)
    store.save()
    return 0 if added else 1


def cmd_restore(args: argparse.Namespace) -> int:
    store = _load()
    # Every profile, exactly like Manager > About > Restore all archived shortcuts:
    # this is what people run before deleting the data folder.
    restored = archive_mod.restore_everything(store.profiles, store.settings.archive_mode)
    store.save()
    if restored == 0:
        print("nothing to restore - no archived shortcuts found")
    else:
        print("restored " + str(restored) + " item(s)")
    return 0


def cmd_autostart(args: argparse.Namespace) -> int:
    state = shell.set_autostart(not args.off)
    print("autostart " + ("on" if state else "off"))
    return 0 if state != args.off else 1


def cmd_export(args: argparse.Namespace) -> int:
    """Write a portable bundle: the store plus every archived/docked file."""
    store = _load()
    target = Path(args.path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.suffix.lower() == ".zip":
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("store.json", json.dumps(store.to_dict(), indent=2, ensure_ascii=False))
            for folder_name in ("archived", "items", "icons"):
                folder = paths.home_dir() / folder_name
                if not folder.exists():
                    continue
                for path in folder.rglob("*"):
                    if path.is_file():
                        bundle.write(path, str(Path(folder_name) / path.relative_to(folder)))
        print("wrote " + str(target))
        return 0
    target.write_text(json.dumps(store.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    print("wrote " + str(target))
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    store = _load()
    source = Path(args.path)
    if not source.exists():
        print("no such file: " + str(source), file=sys.stderr)
        return 1
    if source.suffix.lower() == ".zip":
        with zipfile.ZipFile(source) as bundle:
            raw = json.loads(bundle.read("store.json").decode("utf-8"))
            home = paths.home_dir().resolve()
            for member in bundle.namelist():
                if member == "store.json" or member.endswith("/"):
                    continue
                destination = (home / member).resolve()
                # Only into the folders an export writes, never elsewhere ("zip slip").
                top = member.replace("\\", "/").split("/", 1)[0]
                if top not in ("archived", "items", "icons") or home not in destination.parents:
                    print("skipped unsafe entry: " + member, file=sys.stderr)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as reader, open(destination, "wb") as writer:
                    shutil.copyfileobj(reader, writer)
    else:
        raw = json.loads(source.read_text(encoding="utf-8"))
    merged = Store.from_dict(raw, path=store.path)
    # Restore into the active profile: an export is a snapshot of the docks, so
    # importing it should bring those docks back instead of adding a duplicate
    # profile of the same name.
    restored = 0
    active = store.active_profile
    for folder in merged.active_profile.folders:
        active.folders.append(folder)
        restored += 1
    if not restored:
        existing = {p.name for p in store.profiles}
        for profile in merged.profiles:
            if profile.name in existing:
                profile.name = profile.name + " (imported)"
            store.profiles.append(profile)
    store.save()
    print("imported " + str(restored) + " dock(s) into " + active.name)
    return 0


def _count_archived() -> int:
    total = 0
    root = paths.archive_dir()
    if root.exists():
        for path in root.rglob("*"):
            if path.is_file():
                total += 1
    return total


def _tk_version() -> str:
    try:
        import tkinter

        root = tkinter.Tk()
        root.withdraw()
        version = str(tkinter.TkVersion)
        root.destroy()
        return version
    except Exception as exc:  # pragma: no cover - depends on the display
        return "unavailable: " + str(exc)


class _Parser(argparse.ArgumentParser):
    """An ArgumentParser that returns an exit code instead of raising."""

    def exit(self, status: int = 0, message: str | None = None) -> None:  # type: ignore[override]
        if message:
            self._print_message(message, sys.stderr)
        raise _ParserExit(status)


class _ParserExit(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(status)
        self.status = status


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="mesadock", description="MesaDock - docks for your desktop shortcuts")
    parser.add_argument("--version", action="version", version="MesaDock " + _version())
    sub = parser.add_subparsers(dest="command")

    doctor = sub.add_parser("doctor", help="print environment diagnostics")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=cmd_doctor)

    listing = sub.add_parser("list", help="list docks and items")
    listing.set_defaults(func=cmd_list)

    add = sub.add_parser("add", help="add files, folders or URLs to a dock")
    add.add_argument("paths", nargs="+", help="files, folders or URLs")
    add.add_argument("--dock", default="New dock", help="target dock name (created when missing)")
    add.add_argument("--style", default="grid", choices=["grid", "column", "row", "fan", "ring"])
    add.set_defaults(func=cmd_add)

    restore = sub.add_parser("restore", help="put archived desktop items back")
    restore.set_defaults(func=cmd_restore)

    autostart = sub.add_parser("autostart", help="enable or disable start at logon")
    autostart.add_argument("--off", action="store_true")
    autostart.set_defaults(func=cmd_autostart)

    export = sub.add_parser("export", help="write a portable .zip bundle of everything")
    export.add_argument("path")
    export.set_defaults(func=cmd_export)

    importer = sub.add_parser("import", help="merge a bundle written by export")
    importer.add_argument("path")
    importer.set_defaults(func=cmd_import)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except _ParserExit as exc:
        return exc.status
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())

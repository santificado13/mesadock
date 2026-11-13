"""The command line surface: doctor, list, add, restore, autostart, export/import."""
from __future__ import annotations

import json
import zipfile

from mesadock import __version__, cli


def run(capsys, *argv):
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_doctor_reports_the_environment(capsys, home):
    code, out, _ = run(capsys, "doctor")
    assert code == 0
    assert "MesaDock" in out
    assert __version__ in out
    assert "data folder" in out.lower()


def test_doctor_json_is_machine_readable(capsys, home):
    code, out, _ = run(capsys, "doctor", "--json")
    payload = json.loads(out)
    assert code == 0
    assert payload["version"] == __version__
    assert payload["windows"] is True
    assert str(home) in payload["home"]


def test_list_shows_profiles_docks_and_items(capsys, home, store):
    from mesadock.core.models import DockFolder, DockItem
    from mesadock.core.store import Store

    loaded = Store().load()
    folder = DockFolder(name="Work", style="fan")
    folder.add_item(DockItem(name="Notepad", kind="shortcut", target="C:/Windows/notepad.exe"))
    loaded.profiles[0].folders = [folder]
    loaded.save()

    code, out, _ = run(capsys, "list")
    assert code == 0
    assert "Default" in out
    assert "Work" in out
    assert "Notepad" in out


def test_add_creates_a_dock_and_an_item(capsys, home, tmp_path):
    source = tmp_path / "doc.txt"
    source.write_text("hello", encoding="utf-8")

    code, out, _ = run(capsys, "add", str(source), "--dock", "Docs")
    assert code == 0
    assert "Docs" in out

    from mesadock.core.store import Store

    loaded = Store().load()
    names = [f.name for f in loaded.folders]
    assert "Docs" in names


def test_add_a_url(capsys, home):
    code, out, _ = run(capsys, "add", "https://example.com", "--dock", "Links")
    assert code == 0
    from mesadock.core.store import Store

    loaded = Store().load()
    items = [i for f in loaded.folders for i in f.items]
    assert any(i.kind == "url" for i in items)


def test_restore_with_nothing_archived_is_a_no_op(capsys, home):
    code, out, _ = run(capsys, "restore")
    assert code == 0
    assert "nothing" in out.lower() or "0" in out


def test_autostart_toggle_is_reversible(capsys, home, monkeypatch):
    state = {"enabled": False}
    monkeypatch.setattr(cli.shell, "autostart_enabled", lambda: state["enabled"])

    def fake_set(enabled):
        state["enabled"] = enabled

    monkeypatch.setattr(cli.shell, "set_autostart", fake_set)
    code, out, _ = run(capsys, "autostart")
    assert code == 0 and state["enabled"] is True
    code, out, _ = run(capsys, "autostart", "--off")
    assert code == 0 and state["enabled"] is False


def test_export_and_import_round_trip(capsys, home, tmp_path):
    from mesadock.core.models import DockFolder
    from mesadock.core.store import Store

    loaded = Store().load()
    loaded.add_folder(DockFolder(name="Exported"))
    loaded.save()

    archive = tmp_path / "backup.zip"
    code, _, _ = run(capsys, "export", str(archive))
    assert code == 0 and archive.exists()
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
    assert any(name.endswith("store.json") for name in names)

    loaded.profiles[0].folders = []
    loaded.save()
    code, _, _ = run(capsys, "import", str(archive))
    assert code == 0
    assert [f.name for f in Store().load().folders] == ["Exported"]


def test_unknown_command_reports_an_error(capsys, home):
    code = cli.main(["nonsense"])
    assert code != 0


def test_version_flag(capsys, home):
    code = cli.main(["--version"])
    assert code == 0

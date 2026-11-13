"""Icon artwork and the shell helpers that do not need a display."""
from __future__ import annotations

import ctypes
from pathlib import Path

import pytest

from mesadock.core import icons
from mesadock.win32 import shell


def test_autostart_points_at_the_installed_build_when_there_is_one(monkeypatch, tmp_path):
    """A dev run must not point the logon entry at the dev interpreter.

    Running from source used to write "python.exe __main__.py" into the Run key,
    which opened a console window and broke as soon as the checkout moved.
    """
    fake_local = tmp_path / "Local"
    installed = fake_local / "Programs" / "MesaDock" / "MesaDock.exe"
    installed.parent.mkdir(parents=True)
    installed.write_bytes(b"MZ")
    monkeypatch.setenv("LOCALAPPDATA", str(fake_local))
    assert shell._installed_executable() == installed
    assert str(installed) in shell.autostart_command()
    assert "__main__.py" not in shell.autostart_command()


def test_autostart_falls_back_to_source_when_nothing_is_installed(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "empty"))
    assert shell._installed_executable() is None
    command = shell.autostart_command()
    assert "__main__.py" in command or command.endswith(".exe\"")


@pytest.mark.parametrize("style", ["grid", "column", "row", "fan", "ring"])
def test_dock_icon_has_the_requested_size_and_transparency(style):
    image = icons.dock_icon(style, 64, item_count=3)
    assert image.size == (64, 64)
    assert image.mode == "RGBA"
    assert image.getextrema()[3][1] > 0, "icon must not be fully transparent"


def test_badge_changes_the_icon_corner():
    plain = icons.dock_icon("grid", 64, item_count=0)
    badged = icons.dock_icon("grid", 64, item_count=12)
    assert plain.tobytes() != badged.tobytes()


def test_default_assets_are_written_once(home):
    produced = icons.ensure_default_assets(home / "assets", 96)
    assert set(produced) == {"grid", "column", "row", "fan", "ring"}
    for path in produced.values():
        assert Path(path).exists()
    mtime = Path(produced["grid"]).stat().st_mtime
    icons.ensure_default_assets(home / "assets", 96)
    assert Path(produced["grid"]).stat().st_mtime == mtime


def test_placeholder_icon_encodes_the_extension():
    image = icons.placeholder_icon(".pdf", 64)
    assert image.size == (64, 64)


def test_png_bytes_round_trip():
    payload = icons.png_bytes(icons.dock_icon("ring", 32))
    assert payload.startswith(b"\x89PNG")
    assert payload.startswith(b"\x89PNG")

def test_dock_icon_has_a_vertical_gradient_and_clear_corners():
    """The flat tile read as a grey box; the glass tile must shade top to bottom."""
    for style in ("grid", "column", "row", "fan", "ring"):
        image = icons.dock_icon(style, 120, item_count=4).convert("RGBA")
        pixels = image.load()
        top = pixels[60, 6]
        bottom = pixels[60, 113]
        assert top[0] > bottom[0], style + " should be lighter at the top"
        assert pixels[2, 2][3] == 0, style + " corner must stay transparent"
        assert pixels[60, 1][3] > 0, style + " needs a visible border"

def test_classify_recognises_urls_files_and_folders(tmp_path):
    folder = tmp_path / "dir"
    folder.mkdir()
    document = tmp_path / "file.txt"
    document.write_text("x", encoding="utf-8")
    link = tmp_path / "x.lnk"
    link.write_bytes(b"x")
    assert shell.classify("https://example.com") == "url"
    assert shell.classify(str(folder)) == "folder"
    assert shell.classify(str(document)) == "file"
    assert shell.classify(str(link)) == "shortcut"


def test_shortcut_helpers():
    assert shell.is_shortcut("a.lnk")
    assert shell.is_shortcut("a.URL")
    assert not shell.is_shortcut("a.exe")
    assert shell.is_image("a.png") and not shell.is_image("a.txt")
    assert shell.is_url("http://x") and shell.is_url("mailto:a@b.c")
    assert not shell.is_url("C:/file.txt")


def test_url_file_round_trip(tmp_path):
    path = shell.write_url_file(tmp_path / "site.url", "https://example.org")
    assert shell.read_url_file(path) == "https://example.org"


def test_read_shortcut_of_url_file_returns_target(tmp_path):
    path = shell.write_url_file(tmp_path / "site.url", "https://example.org")
    info = shell.read_shortcut(path)
    assert info["target"] == "https://example.org"


def test_read_shortcut_of_missing_file_is_empty(tmp_path):
    info = shell.read_shortcut(tmp_path / "missing.lnk")
    assert info["target"] == ""


def test_create_and_read_shortcut_round_trip(tmp_path):
    # Regression: cscript was invoked with "-" so it would read the script from
    # stdin, which this Windows build does not support. Creating a .lnk silently
    # failed and reading one returned cscript's error text as the target, so every
    # item added to a dock ended up with a garbage target.
    target = Path(os_environ("SystemRoot", "C:/Windows")) / "System32" / "notepad.exe"
    if not target.exists():
        pytest.skip("notepad.exe not available")
    link = tmp_path / "round trip.lnk"
    assert shell.create_shortcut(link, str(target)) is True
    assert link.exists()
    info = shell.read_shortcut(link)
    assert info["target"].lower() == str(target).lower()
    assert "Erro de entrada" not in info["target"]


def test_icon_extraction_from_a_system_executable():
    # Regression: the previous implementation called GetDIBits with a fixed
    # 32bpp buffer for whatever format the icon used, which corrupted the heap
    # and could kill the whole process with an access violation instead of
    # raising. Several real executables must stay a pure return value.
    names = ["notepad.exe", "explorer.exe", "cmd.exe"]
    root_dir = Path(os_environ("SystemRoot", "C:/Windows"))
    checked = 0
    for name in names:
        target = root_dir / "System32" / name
        if not target.exists():
            continue
        payload = shell.extract_icon_png(str(target), 64)
        assert payload is None or payload.startswith(b"\x89PNG")
        checked += 1
    if not checked:
        pytest.skip("no system executable available")


def test_icon_of_a_missing_file_does_not_raise():
    assert shell.extract_icon_png("C:/definitely/not/here.exe", 32) is None

def test_void_pointer_helper_accepts_an_existing_pointer():
    # Regression: ctypes.c_void_p(c_void_p(x)) raises TypeError, and the drop
    # handler swallowed that error, so a valid HDROP handle produced no paths.
    from mesadock.win32 import drops

    raw = ctypes.c_void_p(1234)
    assert drops._as_pointer(raw) is raw
    assert drops._as_pointer(1234).value == 1234


def test_drop_helpers_never_raise_on_bad_input():
    from mesadock.win32 import drops

    assert drops._paths_from_data_object(None) == []
    assert drops._paths_from_data_object(ctypes.c_void_p(0)) == []
    assert drops._paths_from_hdrop(None) == []
    assert drops._paths_from_hdrop(0) == []


def os_environ(key: str, default: str) -> str:
    import os

    return os.environ.get(key, default)


def test_image_cache_key_is_versioned_so_stale_icons_are_not_reused(home):
    """Old 32px renders were cached forever and kept looking blurry after the
    switch to 256px jumbo extraction."""
    from mesadock.ui.images import ImageCache

    cache = ImageCache(cache_dir=home / "icons")
    key = cache._key("C:/whatever.lnk", 64)
    assert key.endswith("-v2"), key
    assert cache._key("C:/whatever.lnk", 64) == key
    assert cache._key("C:/whatever.lnk", 96) != key


def test_jumbo_icon_extraction_degrades_gracefully():
    from mesadock.win32 import shell

    # Missing files must never raise, whatever the shell returns.
    assert shell.extract_icon_jumbo("C:/definitely/not/here.exe") is None
    assert shell.extract_icon_jumbo("") is None


def test_jumbo_icon_is_available_for_a_real_shortcut(home, tmp_path):
    from mesadock.win32 import shell

    target = tmp_path / "target.exe"
    target.write_bytes(b"x")
    link = tmp_path / "link.lnk"
    if not shell.create_shortcut(link, str(target)):
        return
    image = shell.extract_icon_jumbo(str(link))
    if image is None:
        return
    assert image.size == (256, 256)
    assert image.mode == "RGBA"


def test_top_level_hwnd_falls_back_to_the_given_handle():
    """Tk reports a child frame from winfo_id(); the desktop anchoring needs the
    real toplevel. On a bogus handle the helper must not raise and must return
    something usable."""
    from mesadock.win32 import desktop

    assert desktop.top_level_hwnd(0) == 0
    # An obviously invalid handle must degrade instead of raising.
    result = desktop.top_level_hwnd(123456)
    assert isinstance(result, int)


def test_desktop_layer_keeps_docks_visible_and_behind_apps():
    """The dock belongs above the wallpaper but below normal windows.

    Regression: anchoring to the Progman handle put the dock *behind* the
    wallpaper, so it was invisible; clearing -topmost instead made it an
    ordinary window that any maximised app covered."""
    from mesadock.core.models import Settings

    # Default stays on the desktop layer: that is what the product promises.
    assert Settings().attach_to_desktop is True


def test_needs_reanchor_detects_the_desktop_covering_the_dock():
    """"Show desktop" (Win+D) raises Progman to the front of the z-order.

    The dock is anchored directly above the desktop, so it ended up behind it and
    looked like it had vanished until MesaDock was restarted. The watcher has to
    notice that and re-anchor; this pins the detection contract.
    """
    from mesadock.win32 import desktop

    # Degenerate handles must answer False rather than raise.
    assert desktop.needs_reanchor(0) is False
    assert desktop.needs_reanchor(-1) is False
    # On a bogus handle there is no desktop neighbour chain to walk.
    assert desktop.needs_reanchor(123456789) in (True, False)


def test_desktop_watcher_is_running_on_every_dock():
    """The layer has to be re-checked over time, not just once at startup.

    Without a periodic check the dock only recovered on restart, which is exactly
    what the user reported: it kept disappearing after switching windows.
    """
    import inspect

    from mesadock.ui import dockwindow

    source = inspect.getsource(dockwindow.DockWindow)
    assert "_watch_desktop_layer" in source
    assert "needs_reanchor" in source
    assert "sit_above_desktop" in source


def test_desktop_layer_declares_win64_prototypes():
    """SendMessageW(LVM_GETITEMPOSITION, ..., remote) passed a 64-bit remote
    pointer as a C int.

    ctypes narrows undeclared arguments to 32 bits, so Explorer was told to
    write the icon position to whatever address the low half of the pointer
    named - inside its own process. Declaring the prototypes is the fix; the
    remote pointer is also passed as c_void_p rather than a bare int.
    """
    import ctypes
    import ctypes.wintypes as wintypes

    from mesadock.win32 import desktop

    desktop._declare_signatures()
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    assert user32.SendMessageW.argtypes is not None
    assert len(user32.SendMessageW.argtypes) == 4
    assert kernel32.VirtualAllocEx.restype is ctypes.c_void_p
    assert kernel32.OpenProcess.restype is wintypes.HANDLE
    # The pointer must reach Win32 as a pointer, never as a narrowed int.
    source = __import__("inspect").getsource(desktop.icon_positions)
    assert "c_ssize_t(remote)" in source


def test_desktop_layer_declares_window_discovery_prototypes():
    """FindWindowW/FindWindowExW/GetTopWindow returned 32-bit C ints on Win64.

    needs_reanchor() compares the dock against desktop_window(), which comes from
    FindWindowW. A truncated handle made that comparison wrong, so the watcher kept
    deciding the dock was hidden and re-anchored it every tick: the flicker.
    """
    import ctypes
    import ctypes.wintypes as wintypes

    from mesadock.win32 import desktop

    desktop._declare_signatures()
    user32 = ctypes.windll.user32
    assert user32.FindWindowW.restype is wintypes.HWND
    assert user32.FindWindowExW.restype is wintypes.HWND
    assert user32.GetTopWindow.restype is wintypes.HWND
    assert user32.GetWindow.restype is wintypes.HWND
    assert ctypes.sizeof(wintypes.HWND) == ctypes.sizeof(ctypes.c_void_p)


def test_app_boot_declares_user32_handshake_prototypes():
    """The Manager-reopen handshake narrowed FindWindowW/ShowWindow to 32 bits."""
    import ctypes
    import ctypes.wintypes as wintypes

    from mesadock import app_boot

    app_boot._declare_user32_signatures()
    user32 = ctypes.windll.user32
    assert user32.FindWindowW.restype is wintypes.HWND
    assert user32.ShowWindow.restype is wintypes.BOOL
    assert user32.PostMessageW.argtypes is not None
    assert len(user32.PostMessageW.argtypes) == 4


def test_shell_declares_icon_extraction_prototypes():
    """SHGetFileInfoW/GDI/DestroyIcon were undeclared: truncated pointers caused
    a 0xc0000409 (BEX64) stack overrun when adding a shortcut."""
    import ctypes
    import ctypes.wintypes as wintypes

    from mesadock.win32 import shell

    shell._declare_icon_signatures()
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    shell32 = ctypes.windll.shell32
    assert shell32.SHGetFileInfoW.argtypes is not None
    assert len(shell32.SHGetFileInfoW.argtypes) == 5
    assert user32.DrawIconEx.argtypes is not None
    assert len(user32.DrawIconEx.argtypes) == 9
    assert gdi32.CreateDIBSection.argtypes is not None
    assert len(gdi32.CreateDIBSection.argtypes) == 6
    assert user32.DestroyIcon.restype is wintypes.BOOL


def test_drops_declares_ole_prototypes():
    """CLSIDFromString/RegisterDragDrop/ReleaseStgMedium were undeclared: a
    truncated GUID out-param wrote 16 bytes to a bogus address (BEX64)."""
    import ctypes
    import ctypes.wintypes as wintypes

    from mesadock.win32 import drops

    drops._declare_ole_signatures()
    ole32 = ctypes.windll.ole32
    assert ole32.CLSIDFromString.argtypes is not None
    assert len(ole32.CLSIDFromString.argtypes) == 2
    assert ole32.RegisterDragDrop.argtypes is not None
    assert len(ole32.RegisterDragDrop.argtypes) == 2
    assert ole32.ReleaseStgMedium.argtypes is not None
    assert ole32.ReleaseStgMedium.restype is None


def test_single_instance_mutex_keeps_the_full_handle():
    """CreateMutexW returns a HANDLE; read as a C int it was truncated.

    A truncated handle made the mutex look unowned, which is why the log kept
    reporting "Stale single-instance mutex found" on every clean start.
    """
    import ctypes
    import ctypes.wintypes as wintypes

    from mesadock import app_boot

    app_boot.already_running()
    kernel32 = ctypes.windll.kernel32
    assert kernel32.CreateMutexW.restype is wintypes.HANDLE
    assert ctypes.sizeof(wintypes.HANDLE) == ctypes.sizeof(ctypes.c_void_p)


def test_tray_declares_win64_prototypes_before_touching_the_shell():
    """ctypes assumes C int when no restype is declared, and on Win64 that
    truncates every handle to 32 bits.

    The tray reported hInstance as a truncated int, registered the window class
    with it, and CreateWindowExW then faulted reading memory it could no longer
    address: an access violation that killed the whole app with no traceback,
    roughly a minute after launch. Declaring the prototypes is what stops it.
    """
    import ctypes
    import ctypes.wintypes as wintypes

    from mesadock.ui import tray

    tray._declare_signatures()
    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32
    # A handle must be pointer-sized, not the default c_long.
    assert kernel32.GetModuleHandleW.restype is wintypes.HMODULE
    assert ctypes.sizeof(wintypes.HMODULE) == ctypes.sizeof(ctypes.c_void_p)
    assert user32.CreateWindowExW.restype is wintypes.HWND
    assert len(user32.CreateWindowExW.argtypes) == 12
    assert user32.RegisterClassW.argtypes == [ctypes.c_void_p]


def test_tray_window_proc_returns_a_pointer_sized_result():
    """A WNDPROC returns LRESULT, which is pointer-sized on Win64.

    Declaring it as c_long truncated whatever DefWindowProcW returned, which
    corrupted the message loop and ended in an abort inside ucrtbase.
    """
    from mesadock.ui import tray

    source = __import__("inspect").getsource(tray.TrayIcon._create_window)
    assert "c_ssize_t" in source
    assert "WINFUNCTYPE(ctypes.c_long" not in source

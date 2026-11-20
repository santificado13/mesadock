"""Boot sequence shared by the GUI entry point and the packaged executable."""
from __future__ import annotations
import logging
import os
import sys
import sys
import traceback

from .core import paths


def _ensure_streams() -> None:
    """Give the process a writable stdout/stderr even in a --windowed build.

    PyInstaller's --windowed mode starts the interpreter with no console, so
    sys.stdout and sys.stderr are None. Tkinter's default callback reporter
    writes tracebacks to sys.stderr; when that is None it fails inside the Tcl
    callback and the CRT aborts the process (c0000409, FAST_FAIL_FATAL_APP_EXIT
    subcode 7). Redirecting both streams to the log file means a stray traceback
    is recorded instead of killing the app.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        stream = open(paths.log_file(), "a", encoding="utf-8", buffering=1)
    except OSError:
        stream = open(os.devnull, "w", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


def configure_logging(verbose: bool = False) -> None:
    paths.ensure_dirs()
    _ensure_streams()
    handlers: list[logging.Handler] = [logging.FileHandler(paths.log_file(), encoding="utf-8")]
    if verbose:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )

def _schedule_add_selftest(app, log) -> None:
    """Reproduce the add-shortcut path on demand (MESADOCK_SELFTEST_ADD=1)."""
    from .win32 import shell as shell_mod

    def run() -> None:
        try:
            log.info("SELFTEST: start")
            folder = app.store.folders[0] if app.store.folders else app.add_dock("SELFTEST", "ring")
            log.info("SELFTEST: opening panel")
            app.open_panel(folder, force=True)
            desktop = shell_mod.known_desktop_dir() or paths.home_dir()
            lnk = os.path.join(str(desktop), "__mesadock_selftest__.lnk")
            log.info("SELFTEST: lnk on desktop: %s", lnk)
            shell_mod.create_shortcut(lnk, r"C:\Windows\System32\notepad.exe")
            log.info("SELFTEST: adding path")
            added = app.add_paths_to_dock(folder.id, [lnk])
            log.info("SELFTEST: added=%s", added)
        except Exception:
            log.error("SELFTEST failed:\n%s", traceback.format_exc())

    app.root.after(1500, run)


def run_app(show_manager: bool = False) -> int:
    """Start MesaDock with a single instance guard, DPI and crash logging."""
    configure_logging()

    # Native faults (stack overrun / abort) leave no traceback through logging,
    # so faulthandler dumps the Python stack of every thread to a side file the
    # instant the process dies. This pins the add-shortcut crash in the frozen build.
    try:
        import faulthandler
        _fh = open(str(paths.log_file()) + ".faulthandler", "a", encoding="utf-8", buffering=1)
        faulthandler.enable(file=_fh, all_threads=True)
    except OSError:
        pass
    log = logging.getLogger("mesadock")

    from .win32 import dpi

    mode = dpi.enable_per_monitor_v2()
    log.info("DPI awareness: %s", mode)

    if already_running():
        log.info("MesaDock is already running; asking it to open the Manager window")
        notify_existing_instance()
        return 0

    from .ui.app import MesaDockApp

    try:
        app = MesaDockApp()
        # A first run (no docks yet) must show a window: there is nothing on
        # the desktop to interact with, so starting silently would look dead.
        first_run = not app.store.folders
        if show_manager:
            app.start(minimized=False)
        else:
            app.start(minimized=False if first_run else None)
        if os.environ.get("MESADOCK_SELFTEST_ADD"):
            _schedule_add_selftest(app, log)
        app.root.mainloop()
        return 0
    except Exception:
        log.error("MesaDock stopped unexpectedly:\n%s", traceback.format_exc())
        try:
            from tkinter import messagebox

            from .core.i18n import tr

            messagebox.showerror("MesaDock", tr("MesaDock stopped unexpectedly.\n\nSee ") + str(paths.log_file()))
        except Exception:
            pass
        return 1


MUTEX_NAME = "Local\\MesaDock.SingleInstance"
WM_SHOW_MANAGER = 0x0400 + 21  # WM_USER + 21, posted to the tray window


def already_running() -> bool:
    """True when another live MesaDock instance owns the single-instance mutex.

    A crashed or half-dead instance can leave the mutex behind, which would make
    every later launch exit silently. So the mutex is only trusted when a MesaDock
    window or process actually exists; otherwise it is released and reused.
    """
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        # CreateMutexW returns a HANDLE. Without restype ctypes reads it as a C
        # int, so the 64-bit handle was truncated and the mutex looked released.
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.GetLastError.argtypes = []
        kernel32.GetLastError.restype = wintypes.DWORD
        handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        last_error = ctypes.windll.kernel32.GetLastError()
        globals()["_MUTEX_HANDLE"] = handle
        if last_error != 183:  # ERROR_ALREADY_EXISTS
            return False
        if _a_mesadock_window_exists():
            return True
        logging.getLogger("mesadock").warning(
            "Stale single-instance mutex found; no MesaDock window is alive, taking over")
        return False
    except (AttributeError, OSError):
        return False


def _declare_user32_signatures() -> None:
    """Declare the Win64 prototypes for the single-instance handshake.

    FindWindowW and ShowWindow were undeclared, so ctypes narrowed their HWND
    arguments and return values to 32-bit C ints on Win64. A truncated handle can
    match the wrong window (or none), which made the "ask the running instance to
    open the Manager" path flaky. Same handle-truncation family as the tray crash.
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL


def _a_mesadock_window_exists() -> bool:
    """True when a MesaDock window is on screen (Manager, dock or tray)."""
    try:
        import ctypes
        _declare_user32_signatures()

        user32 = ctypes.windll.user32
        for cls, title in (("MesaDockTrayWindow", None), (None, "MesaDock Manager")):
            if user32.FindWindowW(cls, title):
                return True
        return False
    except (AttributeError, OSError):
        return False


def notify_existing_instance() -> bool:
    """Ask the running instance to surface its Manager window.

    Three independent channels, because any one of them can be unavailable:
    the Manager window (already open), the tray window (always exists while
    the app runs), and a handshake file the running app polls.
    """
    delivered = False
    try:
        import ctypes
        _declare_user32_signatures()

        user32 = ctypes.windll.user32
        from .core import i18n

        # The title is translated, and the running instance may use either language.
        manager = 0
        for title in ("MesaDock Manager", i18n._PT.get("MesaDock Manager", "")):
            manager = manager or user32.FindWindowW(None, title)
        if manager:
            user32.ShowWindow(manager, 9)  # SW_RESTORE
            user32.SetForegroundWindow(manager)
            delivered = True
        tray = user32.FindWindowW("MesaDockTrayWindow", None)
        if tray:
            user32.PostMessageW(tray, WM_SHOW_MANAGER, 0, 0)
            delivered = True
    except (AttributeError, OSError):
        pass
    try:
        paths.show_request_file().write_text("1", encoding="utf-8")
        delivered = True
    except OSError:
        pass
    return delivered

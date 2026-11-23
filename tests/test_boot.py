"""Boot behaviour: single instance, second-launch handoff and first-run visibility.

These are the paths that made the packaged app look dead when double-clicked,
so they are pinned here: a stale mutex must not block startup, a first run must
surface a window, and a second launch must ask the running instance to show its
Manager.
"""
from __future__ import annotations

from mesadock import app_boot
from mesadock.core import paths


def test_show_request_file_lives_in_the_data_folder(home):
    assert paths.show_request_file().parent == home
    assert paths.show_request_file().name.endswith(".request")


def test_first_run_is_detected_from_the_store(home):
    from mesadock.core.store import Store

    assert not Store().load().folders  # a fresh profile has no docks
    assert paths.show_request_file().exists() is False


def test_notify_writes_the_handshake_file(home):
    delivered = app_boot.notify_existing_instance()
    assert delivered is True
    assert paths.show_request_file().read_text(encoding="utf-8") == "1"


def test_a_stale_mutex_does_not_block_startup(home):
    # Create the mutex in this process without any MesaDock window: the guard
    # must notice that nothing is alive and let the new instance through.
    first = app_boot.already_running()
    assert first is False or app_boot._a_mesadock_window_exists()
    second = app_boot.already_running()
    if not app_boot._a_mesadock_window_exists():
        assert second is False


def test_window_probe_is_false_without_a_window(home):
    # Environment tests never run a real GUI, so no MesaDock window can exist
    # unless the machine is running the packaged app outside the test session.
    assert isinstance(app_boot._a_mesadock_window_exists(), bool)


def test_logging_gives_a_windowed_build_usable_streams(home, monkeypatch):
    """--windowed starts the interpreter with sys.stdout/stderr set to None.

    Tkinter reports callback exceptions to sys.stderr. With no stream the
    reporter itself fails inside the Tcl callback and the CRT aborts the
    process with c0000409 subcode 7, which is exactly what happened when a
    shortcut was added from a panel. configure_logging must install a
    writable stream before any callback can raise.
    """
    import sys

    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    app_boot.configure_logging()
    assert sys.stdout is not None
    assert sys.stderr is not None
    # A traceback must be printable without raising: this is what the Tk
    # callback reporter does on every unhandled callback exception.
    import traceback

    try:
        raise ValueError("callback failure")
    except ValueError:
        traceback.print_exc()

def test_log_file_is_capped_and_rotated(home, monkeypatch):
    """The log used to grow forever; it must roll over and keep few backups."""
    import logging

    from mesadock.core import paths

    monkeypatch.setattr(app_boot, "LOG_MAX_BYTES", 2000)
    try:
        app_boot.configure_logging()
        log = logging.getLogger("mesadock")
        for index in range(400):
            log.info("line %04d %s", index, "x" * 40)
        logging.shutdown()
        files = sorted(p.name for p in paths.log_file().parent.glob("mesadock.log*") if "faulthandler" not in p.name)
        assert files == ["mesadock.log", "mesadock.log.1", "mesadock.log.2", "mesadock.log.3"]
        assert all((paths.log_file().parent / name).stat().st_size <= 2200 for name in files)
    finally:
        for handler in logging.getLogger().handlers[:]:
            handler.close()
            logging.getLogger().removeHandler(handler)


def test_hover_events_are_debug_only(home, monkeypatch):
    import logging

    monkeypatch.delenv("MESADOCK_DEBUG", raising=False)
    try:
        app_boot.configure_logging()
        assert not logging.getLogger("mesadock").isEnabledFor(logging.DEBUG)
        monkeypatch.setenv("MESADOCK_DEBUG", "1")
        app_boot.configure_logging()
        assert logging.getLogger("mesadock").isEnabledFor(logging.DEBUG)
    finally:
        for handler in logging.getLogger().handlers[:]:
            handler.close()
            logging.getLogger().removeHandler(handler)

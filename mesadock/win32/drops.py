"""Drag and drop of shortcuts onto docks.

Two mechanisms are supported, in this order:

1. OLE drag and drop (registered with RegisterDragDrop): Explorer sends real
   Shell items, and MesaDock hands them to the app without polling.
2. A pointer-polling fallback, which highlights the dock under the cursor
   while any button is physically down and, when the button is released over a
   dock, asks the clipboard (CF_HDROP) for the files Explorer just copied. This
   keeps dropping usable even when OLE cannot be registered.

The whole module is optional: without Windows, or with MESADOCK_NO_DESKTOP=1,
accept_drops() returns False and nothing else in the app changes.
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from typing import Callable

from . import desktop_enabled
from .desktop import top_level_hwnd

DROPEFFECT_COPY = 1
DROPEFFECT_MOVE = 2
DROPEFFECT_LINK = 4

CF_HDROP = 15
VK_LBUTTON = 0x01
MK_LBUTTON = 0x0001


class _Guid(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    def __init__(self, text: str = "") -> None:
        super().__init__()
        if text:
            self.set(text)

    def set(self, text: str) -> None:
        ctypes.windll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(self))


class _FormatEtc(ctypes.Structure):
    _fields_ = [
        ("cfFormat", wintypes.WORD),
        ("ptd", ctypes.c_void_p),
        ("dwAspect", wintypes.DWORD),
        ("lindex", wintypes.LONG),
        ("tymed", wintypes.DWORD),
    ]


class _DropFiles(ctypes.Structure):
    _fields_ = [
        ("pFiles", wintypes.DWORD),
        ("pt", wintypes.POINT),
        ("fNC", wintypes.BOOL),
        ("fWide", wintypes.BOOL),
    ]


def button_down() -> bool:
    """True while a mouse button is physically held down."""
    if not desktop_enabled():
        return False
    try:
        return bool(ctypes.windll.user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)
    except (AttributeError, OSError):
        return False


def cursor_pos() -> tuple[int, int]:
    if not desktop_enabled():
        return 0, 0
    try:
        point = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
        return int(point.x), int(point.y)
    except (AttributeError, OSError):
        return 0, 0


def _extract_paths(data_handle: int) -> list[str]:
    if not data_handle:
        return []
    path = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.shlwapi.PathCreateFromUrlW(path, 32768)
    if length < 0:
        return []
    return [path.value]


def clipboard_files() -> list[str]:
    """Files (CF_HDROP) currently on the clipboard."""
    if not desktop_enabled():
        return []
    try:
        user32 = ctypes.windll.user32
        # GetClipboardData returns a handle: without restype ctypes truncates it
        # to a C int and the next DragQueryFileW call reads a bogus address.
        user32.GetClipboardData.argtypes = [wintypes.UINT]
        user32.GetClipboardData.restype = ctypes.c_void_p
        if not user32.OpenClipboard(None):
            return []
        try:
            if not user32.IsClipboardFormatAvailable(CF_HDROP):
                return []
            handle = user32.GetClipboardData(CF_HDROP)
            return _paths_from_hdrop(handle)
        finally:
            user32.CloseClipboard()
    except (AttributeError, OSError, TypeError):
        return []

class DropWatcher:
    """Polls the pointer while a drag is in progress and reports the drop."""

    def __init__(self, app, hit_test: Callable[[int, int], object | None],
                 on_enter: Callable[[object], None],
                 on_leave: Callable[[object], None],
                 on_drop: Callable[[object, list[str]], None],
                 interval_ms: int = 60) -> None:
        self.app = app
        self.hit_test = hit_test
        self.on_enter = on_enter
        self.on_leave = on_leave
        self.on_drop = on_drop
        self.interval_ms = interval_ms
        self._job = None
        self._target = None
        self._was_down = False
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._tick()

    def stop(self) -> None:
        self._running = False
        if self._job is not None:
            try:
                self.app.root.after_cancel(self._job)
            except Exception:
                pass
            self._job = None

    def _tick(self) -> None:
        self._job = None
        if not self._running:
            return
        down = button_down()
        x, y = cursor_pos()
        target = self.hit_test(x, y) if down else None
        if target is not self._target:
            if self._target is not None:
                self.on_leave(self._target)
            self._target = target
            if target is not None:
                self.on_enter(target)
        if self._was_down and not down and self._target is not None:
            paths = clipboard_files()
            target_dock = self._target
            self._target = None
            self.on_leave(target_dock)
            if paths:
                self.on_drop(target_dock, paths)
        self._was_down = down
        try:
            self._job = self.app.root.after(self.interval_ms, self._tick)
        except Exception:
            self._running = False


def _declare_ole_signatures() -> None:
    """Declare the OLE prototypes used by the drag-drop drop target.

    CLSIDFromString, RegisterDragDrop and ReleaseStgMedium were undeclared, so
    ctypes narrowed every pointer (the GUID out-param, the IDropTarget, the
    STGMEDIUM) to a 32-bit C int on Win64. CLSIDFromString then wrote the 16-byte
    GUID to a bogus low address: stack corruption the CRT caught as 0xc0000409
    (BEX64) the moment a shortcut was dropped on a dock.
    """
    ole32 = ctypes.windll.ole32
    ole32.CLSIDFromString.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p]
    ole32.CLSIDFromString.restype = ctypes.c_long
    ole32.OleInitialize.argtypes = [ctypes.c_void_p]
    ole32.OleInitialize.restype = ctypes.c_long
    ole32.RegisterDragDrop.argtypes = [wintypes.HWND, ctypes.c_void_p]
    ole32.RegisterDragDrop.restype = ctypes.c_long
    ole32.ReleaseStgMedium.argtypes = [ctypes.c_void_p]
    ole32.ReleaseStgMedium.restype = None


_WM_DROPFILES = 0x0233
_WS_EX_ACCEPTFILES = 0x00000010
_GWL_EXSTYLE = -20
_GWLP_WNDPROC = -4

_DropProc = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                               wintypes.WPARAM, wintypes.LPARAM)

# hwnd -> (old WNDPROC, drop WNDPROC) so the callback stays alive and every other
# message is routed back to the window's original Tk procedure.
_SUBCLASSED = {}


def _declare_wm_drop_signatures() -> None:
    """Win64 prototypes for WM_DROPFILES: DragAcceptFiles + WNDPROC subclass."""
    user32 = ctypes.windll.user32
    shell32 = ctypes.windll.shell32
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT,
                                       wintypes.WPARAM, wintypes.LPARAM]
    user32.CallWindowProcW.restype = ctypes.c_ssize_t
    shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
    shell32.DragAcceptFiles.restype = None
    shell32.DragFinish.argtypes = [wintypes.HANDLE]
    shell32.DragFinish.restype = None


def _make_drop_proc(callback):
    def wndproc(hwnd, msg, wparam, lparam):
        if msg == _WM_DROPFILES:
            try:
                paths = _paths_from_hdrop(wparam)
                if paths:
                    try:
                        callback(paths)
                    except Exception:
                        pass
                ctypes.windll.shell32.DragFinish(wparam)
            except Exception:
                pass
            return 0
        entry = _SUBCLASSED.get(int(hwnd))
        old_proc = entry[0] if entry else 0
        if old_proc:
            return ctypes.windll.user32.CallWindowProcW(old_proc, hwnd, msg, wparam, lparam)
        return 0
    return _DropProc(wndproc)


def accept_drops(window, callback: Callable[[list[str]], None]) -> bool:
    """Enable native drops on a Tk window via the classic WM_DROPFILES message.

    The OLE IDropTarget (RegisterDragDrop + a hand-built COM vtable) crashed with
    0xc0000409 (stack buffer overrun) in the packaged build, so drops now go
    through DragAcceptFiles + WM_DROPFILES instead: a simpler, message-based path
    with no COM vtable.
    """
    if not desktop_enabled():
        return False
    try:
        _declare_wm_drop_signatures()
        hwnd = top_level_hwnd(int(window.winfo_id()))
        if not hwnd:
            return False
        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        style = user32.GetWindowLongPtrW(hwnd, _GWL_EXSTYLE) | _WS_EX_ACCEPTFILES
        user32.SetWindowLongPtrW(hwnd, _GWL_EXSTYLE, style)
        shell32.DragAcceptFiles(hwnd, True)
        if int(hwnd) in _SUBCLASSED:
            return True
        old_proc = int(user32.GetWindowLongPtrW(hwnd, _GWLP_WNDPROC) or 0)
        drop_proc = _make_drop_proc(callback)
        user32.SetWindowLongPtrW(hwnd, _GWLP_WNDPROC, drop_proc)
        _SUBCLASSED[int(hwnd)] = (old_proc, drop_proc)
        return True
    except Exception:
        return False

_TARGETS: dict[int, "_DropTarget"] = {}

DVASPECT_CONTENT = 1
TYMED_HGLOBAL = 1
S_OK = 0
E_NOINTERFACE = -2147467262
E_POINTER = -2147467261


class _StgMedium(ctypes.Structure):
    _fields_ = [
        ("tymed", wintypes.DWORD),
        ("hGlobal", ctypes.c_void_p),
        ("pUnkForRelease", ctypes.c_void_p),
    ]


_HRESULT = ctypes.c_long
_ULONG = ctypes.c_ulong

_QI_FN = ctypes.WINFUNCTYPE(_HRESULT, ctypes.c_void_p, ctypes.POINTER(_Guid),
                            ctypes.POINTER(ctypes.c_void_p))
_ADDREF_FN = ctypes.WINFUNCTYPE(_ULONG, ctypes.c_void_p)
_RELEASE_FN = ctypes.WINFUNCTYPE(_ULONG, ctypes.c_void_p)
_DRAGENTER_FN = ctypes.WINFUNCTYPE(_HRESULT, ctypes.c_void_p, ctypes.c_void_p,
                                    wintypes.DWORD, wintypes.POINT,
                                    ctypes.POINTER(wintypes.DWORD))
_DRAGOVER_FN = ctypes.WINFUNCTYPE(_HRESULT, ctypes.c_void_p, wintypes.DWORD,
                                   wintypes.POINT, ctypes.POINTER(wintypes.DWORD))
_DRAGLEAVE_FN = ctypes.WINFUNCTYPE(_HRESULT, ctypes.c_void_p)
_DROP_FN = ctypes.WINFUNCTYPE(_HRESULT, ctypes.c_void_p, ctypes.c_void_p,
                               wintypes.DWORD, wintypes.POINT,
                               ctypes.POINTER(wintypes.DWORD))
_GETDATA_FN = ctypes.WINFUNCTYPE(_HRESULT, ctypes.c_void_p,
                                 ctypes.POINTER(_FormatEtc),
                                 ctypes.POINTER(_StgMedium))


class _DropTargetVtbl(ctypes.Structure):
    _fields_ = [
        ("QueryInterface", _QI_FN),
        ("AddRef", _ADDREF_FN),
        ("Release", _RELEASE_FN),
        ("DragEnter", _DRAGENTER_FN),
        ("DragOver", _DRAGOVER_FN),
        ("DragLeave", _DRAGLEAVE_FN),
        ("Drop", _DROP_FN),
    ]


class _DropTargetObject(ctypes.Structure):
    _fields_ = [("lpVtbl", ctypes.POINTER(_DropTargetVtbl))]


def _same_guid(first: _Guid, second: _Guid) -> bool:
    size = ctypes.sizeof(_Guid)
    return ctypes.string_at(ctypes.byref(first), size) == ctypes.string_at(ctypes.byref(second), size)


def _shell32() -> "ctypes.WinDLL":
    """shell32 with DragQueryFileW typed correctly.

    Without argtypes ctypes passes and returns C ints, which truncates the
    64-bit HDROP handle on 64-bit Windows: the first call appears to work and
    the next one raises an access violation. Every call here goes through this
    helper so the handle stays a full pointer.
    """
    shell32 = ctypes.windll.shell32
    shell32.DragQueryFileW.argtypes = [ctypes.c_void_p, wintypes.UINT,
                                       ctypes.c_wchar_p, wintypes.UINT]
    shell32.DragQueryFileW.restype = wintypes.UINT
    return shell32


def _paths_from_hdrop(handle) -> list[str]:
    """File paths inside an HDROP handle, using typed DragQueryFileW calls."""
    if not handle:
        return []
    try:
        shell32 = _shell32()
        pointer = ctypes.c_void_p(handle)
        total = int(shell32.DragQueryFileW(pointer, 0xFFFFFFFF, None, 0))
        paths: list[str] = []
        for index in range(max(0, total)):
            size = int(shell32.DragQueryFileW(pointer, index, None, 0))
            buffer = ctypes.create_unicode_buffer(size + 2)
            shell32.DragQueryFileW(pointer, index, buffer, size + 2)
            if buffer.value:
                paths.append(buffer.value)
        return paths
    except (AttributeError, OSError, ValueError):
        return []


def _as_pointer(value) -> ctypes.c_void_p:
    """A c_void_p for a handle that may already be a c_void_p.

    ctypes.c_void_p(c_void_p(...)) raises TypeError, and the caller used to swallow
    it, so a perfectly valid handle silently produced an empty path list.
    """
    if isinstance(value, ctypes.c_void_p):
        return value
    return ctypes.c_void_p(value)


def _paths_from_data_object(data_object) -> list[str]:
    """Read CF_HDROP out of the IDataObject an Explorer drag hands us."""
    if not data_object:
        return []
    medium = _StgMedium()
    try:
        fmt = _FormatEtc()
        fmt.cfFormat = CF_HDROP
        fmt.ptd = None
        fmt.dwAspect = DVASPECT_CONTENT
        fmt.lindex = -1
        fmt.tymed = TYMED_HGLOBAL
        table = ctypes.cast(data_object, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        get_data = _GETDATA_FN(table[3])
        if get_data(_as_pointer(data_object), ctypes.byref(fmt), ctypes.byref(medium)) != S_OK:
            return []
        try:
            return _paths_from_hdrop(medium.hGlobal)
        finally:
            ctypes.windll.ole32.ReleaseStgMedium(ctypes.byref(medium))
    except Exception:
        return []


class _DropTarget:
    """Minimal IDropTarget, enough for Explorer to hand us dropped files."""

    def __init__(self, hwnd: int, callback: Callable[[list[str]], None]) -> None:
        self.hwnd = int(hwnd)
        self.callback = callback
        self.refs = 1
        self._iid_unknown = _Guid()
        self._iid_drop = _Guid()
        ctypes.windll.ole32.CLSIDFromString(
            ctypes.c_wchar_p("{00000000-0000-0000-C000-000000000046}"),
            ctypes.byref(self._iid_unknown))
        ctypes.windll.ole32.CLSIDFromString(
            ctypes.c_wchar_p("{00000122-0000-0000-C000-000000000046}"),
            ctypes.byref(self._iid_drop))
        self.vtbl = _DropTargetVtbl()
        self.vtbl.QueryInterface = _QI_FN(self._query_interface)
        self.vtbl.AddRef = _ADDREF_FN(self._add_ref)
        self.vtbl.Release = _RELEASE_FN(self._release)
        self.vtbl.DragEnter = _DRAGENTER_FN(self._drag_enter)
        self.vtbl.DragOver = _DRAGOVER_FN(self._drag_over)
        self.vtbl.DragLeave = _DRAGLEAVE_FN(self._drag_leave)
        self.vtbl.Drop = _DROP_FN(self._drop)
        self.object = _DropTargetObject()
        self.object.lpVtbl = ctypes.pointer(self.vtbl)
        self.pointer = ctypes.cast(ctypes.pointer(self.object), ctypes.c_void_p)

    def register(self) -> bool:
        try:
            result = ctypes.windll.ole32.RegisterDragDrop(ctypes.c_void_p(self.hwnd), self.pointer)
            return int(result) == S_OK
        except Exception:
            return False

    def _query_interface(self, this, riid, out):
        if not out:
            return E_POINTER
        try:
            wanted = riid.contents
        except (AttributeError, ValueError):
            out[0] = None
            return E_NOINTERFACE
        if _same_guid(wanted, self._iid_unknown) or _same_guid(wanted, self._iid_drop):
            out[0] = self.pointer
            self.refs += 1
            return S_OK
        out[0] = None
        return E_NOINTERFACE

    def _add_ref(self, this):
        self.refs += 1
        return self.refs

    def _release(self, this):
        self.refs -= 1
        return max(1, self.refs)

    def _drag_enter(self, this, data_object, key_state, point, effect):
        if effect:
            effect[0] = DROPEFFECT_COPY
        return S_OK

    def _drag_over(self, this, key_state, point, effect):
        if effect:
            effect[0] = DROPEFFECT_COPY
        return S_OK

    def _drag_leave(self, this):
        return S_OK

    def _drop(self, this, data_object, key_state, point, effect):
        if effect:
            effect[0] = DROPEFFECT_COPY
        paths = _paths_from_data_object(data_object)
        if paths:
            try:
                self.callback(paths)
            except Exception:
                pass
        return S_OK


def _register(hwnd: int, callback: Callable[[list[str]], None]) -> bool:
    """Register a real OLE IDropTarget on hwnd.

    This is the only way to receive an Explorer drag: during a drag the source
    hands the target an IDataObject and the clipboard stays empty, so the
    polling fallback can highlight a dock but can never learn which files were
    dropped. Registering for real is what makes drag and drop actually work.
    """
    existing = _TARGETS.get(int(hwnd))
    if existing is not None:
        existing.callback = callback
        return True
    try:
        target = _DropTarget(hwnd, callback)
    except Exception:
        return False
    if not target.register():
        return False
    _TARGETS[int(hwnd)] = target
    return True


def drop_paths_from_clipboard() -> list[str]:
    """Public alias used by the app when a drop is detected."""
    return clipboard_files()


def wait_for_button_release(timeout: float = 2.0) -> bool:
    """Block until the left button is released (used by tests and helpers)."""
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        if not button_down():
            return True
        time.sleep(0.02)
    return False

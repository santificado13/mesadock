"""System tray icon via Shell_NotifyIcon.

The icon lives in a message-only Win32 window whose messages are pumped by
the Tk main loop via root.after(). Menu actions are marshalled to Tk with
root.after(0, ...). When the shell is unavailable (headless CI, Explorer not
running) start() reports the failure and the app keeps working without a tray.
"""
from __future__ import annotations

import ctypes
import tkinter as tk
from ctypes import wintypes

from ..core.i18n import tr
from . import theme

WM_USER = 0x0400
WM_TRAYICON = WM_USER + 20
WM_SHOW_MANAGER = WM_USER + 21  # posted by a second launch (see app_boot)
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
NIM_ADD = 0
NIM_MODIFY = 1
NIM_DELETE = 2
NIF_MESSAGE = 0x01
NIF_ICON = 0x02
NIF_TIP = 0x04
NIF_INFO = 0x10
NIIF_INFO = 0x01
MF_STRING = 0x0000
MF_SEPARATOR = 0x0800
TPM_LEFTALIGN = 0x0000
TPM_RIGHTBUTTON = 0x0002
TPM_BOTTOMALIGN = 0x0020
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
LR_DEFAULTSIZE = 0x0040
IDI_APPLICATION = 32512

TRAY_UID = 1
TRAY_TIP = "MesaDock"


def _declare_signatures() -> None:
    """Give ctypes the real Win64 prototypes for every call used below.

    Without argtypes/restype ctypes assumes a C int everywhere: a 32-bit
    return truncates any pointer or handle, and a 64-bit argument is passed
    as a truncated pointer. That is not a warning, it is an access violation:
    GetModuleHandleW returned a 32-bit hInstance, and CreateWindowExW then
    faulted while reading the WNDCLASSW it could no longer address.
    """
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    shell32 = ctypes.windll.shell32

    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE

    user32.RegisterClassW.argtypes = [ctypes.c_void_p]
    user32.RegisterClassW.restype = wintypes.ATOM

    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND

    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.restype = wintypes.BOOL
    user32.PostQuitMessage.argtypes = [ctypes.c_int]
    user32.PostQuitMessage.restype = None
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                   wintypes.UINT, wintypes.UINT, wintypes.UINT]
    user32.PeekMessageW.restype = wintypes.BOOL
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.TranslateMessage.restype = wintypes.BOOL
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.restype = ctypes.c_ssize_t
    user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                                  ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.LoadImageW.restype = wintypes.HANDLE
    user32.LoadIconW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
    user32.LoadIconW.restype = wintypes.HANDLE

    shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.c_void_p]
    shell32.Shell_NotifyIconW.restype = wintypes.BOOL


class NOTIFYICONDATAW(ctypes.Structure):
    """The Windows NOTIFYICONDATAW layout used by Shell_NotifyIcon."""

    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", wintypes.HICON),
    ]


def _build_notify_icon_data(icon_path: str | None, hwnd: int, uid: int = TRAY_UID,
                            tip: str = TRAY_TIP) -> NOTIFYICONDATAW:
    """Fill a NOTIFYICONDATAW for the given window and icon file."""
    data = NOTIFYICONDATAW()
    data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
    data.hWnd = hwnd
    data.uID = uid
    data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
    data.uCallbackMessage = WM_TRAYICON
    data.hIcon = _load_icon(icon_path)
    data.szTip = tip[:127]
    return data


def _def_window_proc(hwnd, msg, wparam, lparam) -> int:
    """DefWindowProcW with explicit signatures (avoids ctypes int overflow)."""
    try:
        user32 = ctypes.windll.user32
        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
        user32.DefWindowProcW.restype = ctypes.c_ssize_t
        return int(user32.DefWindowProcW(hwnd, msg, ctypes.c_size_t(wparam), ctypes.c_ssize_t(lparam)))
    except (AttributeError, OSError, ctypes.ArgumentError):
        return 0


def _load_icon(icon_path: str | None) -> int:
    """HICON from a file, falling back to the stock application icon."""
    try:
        user32 = ctypes.windll.user32
        if icon_path:
            handle = user32.LoadImageW(None, str(icon_path), IMAGE_ICON, 0, 0,
                                       LR_LOADFROMFILE | LR_DEFAULTSIZE)
            if handle:
                return int(handle)
        return int(user32.LoadIconW(None, IDI_APPLICATION))
    except (AttributeError, OSError):
        return 0


class TrayIcon:
    """Owns the shell notification icon and its context menu.

    Messages are pumped by the Tk main loop via root.after().
    """

    def __init__(self, app, icon_path: str | None = None) -> None:
        self.app = app
        self.icon_path = icon_path
        self._hwnd = 0
        self._running = False
        self._error: str | None = None
        self._pump_job: str | None = None
        self._wndproc_ref = None  # keep callback alive

    # -- public API --------------------------------------------------------
    def start(self) -> bool:
        """Add the tray icon; returns False when the shell refuses it."""
        if self._running:
            return True
        try:
            self._create_window()
        except Exception as exc:
            self._error = str(exc)
            return False
        self._running = True
        # Start pumping messages via Tk's event loop
        self._pump_messages()
        return self._running

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._pump_job is not None:
            try:
                self.app.root.after_cancel(self._pump_job)
            except tk.TclError:
                pass
            self._pump_job = None
        if self._hwnd:
            try:
                ctypes.windll.user32.DestroyWindow(self._hwnd)
            except (AttributeError, OSError):
                pass
            self._hwnd = 0

    def is_running(self) -> bool:
        return self._running

    def notify(self, message: str, title: str = TRAY_TIP) -> bool:
        """Show a balloon notification; returns False when unsupported."""
        # Disabled: the NIM_MODIFY + NIF_INFO balloon crashed the process with
        # 0xc0000409 (stack overrun) in the packaged build, right after a drop.
        # The caller falls back to the log, so a toast is lost but the app no
        # longer dies when an item is added.
        return False

    @property
    def error(self) -> str | None:
        return self._error

    # -- window creation ----------------------------------------------------
    def _create_window(self) -> None:
        _declare_signatures()
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        hinstance = kernel32.GetModuleHandleW(None)

        # A window procedure returns LRESULT, which is pointer-sized. WINFUNCTYPE
        # with c_long truncates the result on Win64, so returning a value from
        # DefWindowProcW corrupted the stack of the message loop.
        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                                     wintypes.WPARAM, wintypes.LPARAM)

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        self._wndproc_ref = WNDPROC(self._handle_message)  # keep alive
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._wndproc_ref
        wc.hInstance = hinstance
        wc.lpszClassName = "MesaDockTrayWindow"
        user32.RegisterClassW(ctypes.byref(wc))

        self._hwnd = int(user32.CreateWindowExW(0, "MesaDockTrayWindow", "MesaDock tray", 0,
                                                0, 0, 0, 0, None, None, hinstance, None))
        if not self._hwnd:
            raise RuntimeError("CreateWindowExW failed")

        data = _build_notify_icon_data(self.icon_path, self._hwnd)
        if not ctypes.windll.shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(data)):
            raise RuntimeError("Shell_NotifyIcon(NIM_ADD) refused")
        self._running = True

    # -- message pumping via Tk's event loop --------------------------------
    def _pump_messages(self) -> None:
        if not self._running:
            return
        _declare_signatures()
        user32 = ctypes.windll.user32
        message = wintypes.MSG()
        # PM_REMOVE = 0x0001
        while user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0x0001):
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
        # Re-arm pump
        self._pump_job = self.app.root.after(50, self._pump_messages)

    def _remove_icon(self) -> None:
        try:
            data = _build_notify_icon_data(self.icon_path, self._hwnd)
            ctypes.windll.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(data))
        except (AttributeError, OSError):
            pass

    # -- window procedure --------------------------------------------------
    def _handle_message(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_TRAYICON:
                if lparam == WM_LBUTTONDBLCLK or lparam == WM_LBUTTONUP:
                    self._call_in_tk(self.app.open_manager)
                elif lparam == WM_RBUTTONUP:
                    self._show_menu()
                return 0
            if msg == WM_SHOW_MANAGER:
                self._call_in_tk(self.app.open_manager)
                return 0
            if msg == 0x0010:  # WM_CLOSE
                ctypes.windll.user32.DestroyWindow(hwnd)
                return 0
            if msg == 0x0002:  # WM_DESTROY
                # Don't call PostQuitMessage - we're not running a message loop
                return 0
        except Exception:
            pass
        return _def_window_proc(hwnd, msg, wparam, lparam)

    def _call_in_tk(self, callback) -> None:
        try:
            self.app._enqueue_tk(callback)
        except Exception:
            pass

    def _show_menu(self) -> None:
        try:
            self.app._enqueue_tk(self._popup_on_tk_thread)
        except Exception:
            pass

    def _popup_on_tk_thread(self) -> None:
        try:
            menu = tk.Menu(self.app.root, tearoff=0, bg=theme.BG_ELEVATED, fg=theme.TEXT,
                           activebackground=theme.ACCENT_SOFT, activeforeground=theme.TEXT,
                           borderwidth=0, font=theme.font(9))
            menu.add_command(label=tr("Open Manager"), command=self.app.open_manager)
            menu.add_command(label=tr("New dock"), command=self.app.prompt_new_dock)
            profiles = tk.Menu(menu, tearoff=0, bg=theme.BG_ELEVATED, fg=theme.TEXT,
                               activebackground=theme.ACCENT_SOFT, activeforeground=theme.TEXT,
                               borderwidth=0, font=theme.font(9))
            for index, profile in enumerate(self.app.store.profiles):
                profiles.add_command(label=profile.name,
                                     command=lambda i=index: self.app.switch_profile(i))
            menu.add_cascade(label=tr("Profile"), menu=profiles)
            menu.add_separator()
            menu.add_command(label=tr("Quit MesaDock"), command=self.app.quit)
            x, y = self.app.root.winfo_pointerxy()
            menu.tk_popup(x, y)
        except tk.TclError:
            pass


def tray_available() -> bool:
    """True when the shell notification area can accept an icon."""
    try:
        return bool(ctypes.windll.shell32.Shell_NotifyIconW)
    except (AttributeError, OSError):
        return False
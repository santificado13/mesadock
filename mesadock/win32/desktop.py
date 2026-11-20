"""The live desktop: its window, icon grid and native icon positions.

MesaDock docks sit on the desktop surface itself: they belong to Progman or to
the WorkerW window that hosts the icon view, which keeps them behind normal
application windows exactly like the real desktop icons.

Every function returns a safe default when desktop integration is disabled, so
the rest of the app can call it unconditionally.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from . import desktop_enabled

# Every call in this module talks to Explorer through ctypes. A wrong or missing
# prototype raises ctypes.ArgumentError, which is NOT an OSError, and it used to
# escape into the Tk callback that opened a panel. In the packaged build that
# unhandled exception had no stderr to print to and aborted the process with
# c0000409 (FAST_FAIL_FATAL_APP_EXIT). These helpers are all best-effort, so any
# of those failure modes should degrade to a safe default instead.
_SHELL_ERRORS = (AttributeError, OSError, TypeError, ValueError, ctypes.ArgumentError)

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
LVM_FIRST = 0x1000
LVM_GETITEMCOUNT = LVM_FIRST + 4
LVM_SETITEMPOSITION = LVM_FIRST + 15
LVM_GETITEMPOSITION = LVM_FIRST + 16
LVM_REDRAWITEMS = LVM_FIRST + 21
LVM_GETITEMSPACING = LVM_FIRST + 51

PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
MEM_COMMIT = 0x1000
MEM_RELEASE = 0x8000
MEM_RESERVE = 0x2000
PAGE_READWRITE = 0x04

_EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM) if desktop_enabled() else None


def _declare_signatures() -> None:
    """Give ctypes the real Win64 prototypes for the shell calls used here.

    ctypes assumes a C int when no argtypes are set, which on Win64 quietly
    narrows a 64-bit argument to 32 bits. That was not theoretical:
    SendMessageW(LVM_GETITEMPOSITION, ..., remote) passed a pointer returned by
    VirtualAllocEx as an int, so Explorer wrote the icon position to whatever
    address the low 32 bits happened to name - inside the Explorer process.
    """
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    shell32 = ctypes.windll.shell32

    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                    wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = wintypes.LPARAM
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.SetWindowPos.restype = wintypes.BOOL
    # _EnumWindowsProc is None when the desktop layer is disabled (tests, CI):
    # putting None in argtypes makes ctypes raise on every later call, so the
    # whole block is skipped rather than half-registered.
    if _EnumWindowsProc is not None:
        user32.EnumWindows.argtypes = [_EnumWindowsProc, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int

    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.VirtualAllocEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                        wintypes.DWORD, wintypes.DWORD]
    kernel32.VirtualAllocEx.restype = ctypes.c_void_p
    kernel32.VirtualFreeEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                       wintypes.DWORD]
    kernel32.VirtualFreeEx.restype = wintypes.BOOL
    kernel32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                           ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    kernel32.ReadProcessMemory.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    shell32.SHChangeNotify.argtypes = [wintypes.LONG, wintypes.UINT,
                                       ctypes.c_void_p, ctypes.c_void_p]
    shell32.SHChangeNotify.restype = None

    # Window discovery and z-order walking were also undeclared, so on Win64
    # FindWindowW / FindWindowExW / GetTopWindow returned a 32-bit C int. A
    # truncated desktop handle made needs_reanchor() compare the dock against the
    # wrong window, which produced false "dock is hidden" positives and the dock
    # re-anchored itself over and over: the visible flicker the user reported.
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowExW.restype = wintypes.HWND
    user32.GetTopWindow.argtypes = [wintypes.HWND]
    user32.GetTopWindow.restype = wintypes.HWND
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetWindow.restype = wintypes.HWND
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
    user32.SetParent.restype = wintypes.HWND
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    user32.SetWindowLongW.restype = ctypes.c_long


def find_desktop_listview() -> tuple[int, int] | None:
    """Return (icon ListView handle, host window handle) or None.

    Handles both Windows 10 (SHELLDLL_DefView under Progman) and Windows 11
    22H2+ (SHELLDLL_DefView under a WorkerW band).
    """
    if not desktop_enabled():
        return None
    try:
        user32 = ctypes.windll.user32
        progman = user32.FindWindowW("Progman", None)
        if progman:
            shell = user32.FindWindowExW(progman, None, "SHELLDLL_DefView", None)
            if shell:
                view = user32.FindWindowExW(shell, None, "SysListView32", None)
                if view:
                    return int(view), int(progman)
        found: list[tuple[int, int]] = []

        def callback(hwnd, data):
            shell = user32.FindWindowExW(hwnd, None, "SHELLDLL_DefView", None)
            if shell:
                view = user32.FindWindowExW(shell, None, "SysListView32", None)
                if view:
                    found.append((int(view), int(hwnd)))
                    return False
            return True

        user32.EnumWindows(_EnumWindowsProc(callback), 0)
        return found[0] if found else None
    except _SHELL_ERRORS:
        return None


def desktop_window() -> int | None:
    """Handle of the window that behaves like the desktop, or None."""
    found = find_desktop_listview()
    return found[1] if found else None


def reparent(window_hwnd: int, desktop_hwnd: int | None = None) -> bool:
    """Make a top-level window a child of the desktop window."""
    if not desktop_enabled() or not window_hwnd:
        return False
    parent = desktop_hwnd or desktop_window()
    if not parent:
        return False
    try:
        user32 = ctypes.windll.user32
        user32.SetParent(int(window_hwnd), int(parent))
        style = user32.GetWindowLongW(int(window_hwnd), GWL_EXSTYLE) | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
        user32.SetWindowLongW(int(window_hwnd), GWL_EXSTYLE, style)
        return True
    except _SHELL_ERRORS:
        return False


def top_level_hwnd(hwnd: int) -> int:
    """Real top-level window behind a Tk widget id.

    Tk's winfo_id() returns the *child* window it draws into, not the toplevel
    that owns the frame. SetWindowPos on that child only reorders it inside Tk,
    which is why the desktop anchoring never took effect.
    """
    if not hwnd:
        return 0
    try:
        user32 = ctypes.windll.user32
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        GA_ROOT = 2
        root = int(user32.GetAncestor(int(hwnd), GA_ROOT) or 0)
        return root or int(hwnd)
    except _SHELL_ERRORS:
        return int(hwnd)


def sit_above_desktop(hwnd: int) -> bool:
    """Park a window directly above the desktop, below every normal window.

    A pointer is passed to SetWindowPos, so the Win64 prototypes must be in
    place before the first call or the handle is narrowed to 32 bits.

    SetParent to Progman looks tidy but makes the dock a child of the window that
    sits *behind* SHELLDLL_DefView, so it becomes invisible. Anchoring the z-order
    instead keeps the dock above the wallpaper and below the icons.

    The desktop is not always the bottom window. "Show desktop" (Win+D) raises
    Progman above everything, and a maximised app then sits below it; inserting the
    dock *after* Progman at that moment puts it behind the desktop, so it vanished
    until MesaDock restarted. The anchor is therefore the window immediately above
    the desktop only when the desktop is at the top of the stack; otherwise the
    desktop is already at the bottom and the dock can simply be inserted after it.
    """
    if not desktop_enabled() or not hwnd:
        return False
    anchor = desktop_window()
    if not anchor:
        return False
    try:
        user32 = ctypes.windll.user32
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                         ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                         wintypes.UINT]
        user32.SetWindowPos.restype = wintypes.BOOL
        user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetWindow.restype = wintypes.HWND
        flags = SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_NOOWNERZORDER | SWP_SHOWWINDOW
        # The handle has to be the real toplevel; the widget id Tk reports is only
        # its child frame, and reordering that one changes nothing on screen.
        target = top_level_hwnd(hwnd)
        if not target:
            return False
        # Insert after the *window above the desktop* rather than the desktop
        # itself: that single handle is correct whether the desktop is at the very
        # bottom (always) or has been raised by Show Desktop (temporarily).
        GW_HWNDPREV = 3
        neighbour = int(user32.GetWindow(int(anchor), GW_HWNDPREV) or 0)
        insert_after = neighbour or int(anchor)
        if insert_after == target:
            # The dock is already the window right above the desktop.
            return True
        return bool(user32.SetWindowPos(int(target), int(insert_after), 0, 0, 0, 0, flags))
    except _SHELL_ERRORS:
        return False

def needs_reanchor(hwnd: int) -> bool:
    """True when the dock is not properly parked directly above the desktop."""
    if not desktop_enabled() or not hwnd:
        return False
    anchor = desktop_window()
    if not anchor:
        return False
    try:
        user32 = ctypes.windll.user32
        user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetWindow.restype = wintypes.HWND
        target = top_level_hwnd(hwnd)
        if not target:
            return False
        GW_HWNDNEXT = 2
        walker = int(user32.GetWindow(target, GW_HWNDNEXT) or 0)
        while walker:
            if walker == int(anchor):
                return False
            if user32.IsWindowVisible(walker):
                buf = ctypes.create_unicode_buffer(64)
                user32.GetClassNameW(walker, buf, 64)
                if buf.value not in (
                    "TkTopLevel",
                    "WorkerW",
                    "DummyDWMListenerWindow",
                    "PseudoConsoleWindow",
                    "ThumbnailDeviceHelperWnd",
                ):
                    return True
            walker = int(user32.GetWindow(walker, GW_HWNDNEXT) or 0)
        return True
    except _SHELL_ERRORS:
        return False


def is_child_of_desktop(hwnd: int) -> bool:
    """True when this window is currently parented to the desktop window.

    Uses GetAncestor(GA_PARENT) rather than GetParent: for a window owned by
    Progman, GetParent returns NULL while GetAncestor reports the real parent.
    The old check therefore always failed, so re-attachment never ran and docks
    stayed detached from the desktop.
    """
    if not desktop_enabled() or not hwnd:
        return False
    parent = desktop_window()
    if not parent:
        return False
    try:
        user32 = ctypes.windll.user32
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        GA_PARENT = 1
        found = int(user32.GetAncestor(int(hwnd), GA_PARENT) or 0)
        return found == int(parent)
    except _SHELL_ERRORS:
        return False

def icon_spacing() -> tuple[int, int]:
    """Horizontal and vertical spacing of the desktop icon grid, physical pixels."""
    _declare_signatures()
    found = find_desktop_listview()
    if not found:
        return 0, 0
    try:
        result = int(ctypes.windll.user32.SendMessageW(found[0], LVM_GETITEMSPACING, 0, 0))
        return result & 0xFFFF, (result >> 16) & 0xFFFF
    except _SHELL_ERRORS:
        return 0, 0


def icon_grid_cell(monitor=None) -> tuple[int, int]:
    """Icon cell size for a monitor, falling back to a DPI-derived estimate."""
    spacing_x, spacing_y = icon_spacing()
    scale = getattr(monitor, "scale", 1.0) or 1.0
    if spacing_x > 0 and spacing_y > 0:
        return int(spacing_x), int(spacing_y)
    return int(round(76 * scale)), int(round(90 * scale))


def icon_count() -> int:
    found = find_desktop_listview()
    if not found:
        return 0
    try:
        return int(ctypes.windll.user32.SendMessageW(found[0], LVM_GETITEMCOUNT, 0, 0))
    except _SHELL_ERRORS:
        return 0


def icon_positions() -> list[tuple[int, int]]:
    """Screen position of every native desktop icon, in virtual-screen pixels."""
    _declare_signatures()
    found = find_desktop_listview()
    if not found:
        return []
    count = icon_count()
    if count <= 0:
        return []
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(found[0], ctypes.byref(pid))
        access = PROCESS_VM_OPERATION | PROCESS_VM_READ | PROCESS_VM_WRITE
        process = kernel32.OpenProcess(access, False, pid.value)
        if not process:
            return []
        try:
            size = count * ctypes.sizeof(wintypes.POINT)
            remote = kernel32.VirtualAllocEx(process, None, size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
            if not remote:
                return []
            try:
                positions: list[tuple[int, int]] = []
                for index in range(count):
                    # LVM_GETITEMPOSITION takes a POINTER in lParam. LPARAM is
                    # c_longlong on Win64, so the pointer keeps all 64 bits; with
                    # no argtypes at all ctypes assumed a C int and narrowed it,
                    # telling Explorer to write to a bogus low address.
                    user32.SendMessageW(found[0], LVM_GETITEMPOSITION, index,
                                        ctypes.c_ssize_t(remote))
                    point = wintypes.POINT()
                    read = ctypes.c_size_t(0)
                    ok = kernel32.ReadProcessMemory(
                        process,
                        ctypes.c_void_p(remote),
                        ctypes.byref(point),
                        ctypes.sizeof(point),
                        ctypes.byref(read),
                    )
                    if not ok:
                        break
                    positions.append((int(point.x), int(point.y)))
                return positions
            finally:
                kernel32.VirtualFreeEx(process, ctypes.c_void_p(remote), 0, MEM_RELEASE)
        finally:
            kernel32.CloseHandle(process)
    except _SHELL_ERRORS:
        return []


def move_icon(index: int, x: int, y: int) -> bool:
    """Move native desktop icon at index to screen position x, y."""
    _declare_signatures()
    found = find_desktop_listview()
    if not found:
        return False
    try:
        packed = (int(x) & 0xFFFF) | ((int(y) & 0xFFFF) << 16)
        ctypes.windll.user32.SendMessageW(found[0], LVM_SETITEMPOSITION, int(index), packed)
        return True
    except _SHELL_ERRORS:
        return False


def refresh_icons() -> None:
    _declare_signatures()
    found = find_desktop_listview()
    if not found:
        return
    try:
        ctypes.windll.user32.SendMessageW(found[0], LVM_REDRAWITEMS, 0, max(1, icon_count()))
    except _SHELL_ERRORS:
        pass


def icon_rects() -> list[tuple[int, int, int, int]]:
    """Bounding rect of every native icon, for collision avoidance."""
    cell_w, cell_h = icon_grid_cell()
    return [(x, y, cell_w, cell_h) for x, y in icon_positions()]


def apply_desktop_window_styles(hwnd: int, click_through: bool = False) -> bool:
    """Mark a window as a non-activating tool window living on the desktop."""
    if not desktop_enabled() or not hwnd:
        return False
    try:
        user32 = ctypes.windll.user32
        user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongW.restype = ctypes.c_long
        user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
        user32.SetWindowLongW.restype = ctypes.c_long
        # Extended styles belong on the real toplevel: setting them on Tk's child
        # frame left the actual window activating and appearing in the taskbar.
        target = top_level_hwnd(hwnd)
        style = user32.GetWindowLongW(int(target), GWL_EXSTYLE)
        style |= WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        if click_through:
            style |= WS_EX_TRANSPARENT | WS_EX_LAYERED
        user32.SetWindowLongW(int(target), GWL_EXSTYLE, style)
        return True
        return True
    except _SHELL_ERRORS:
        return False


def notify_shell() -> None:
    """Ask Explorer to repaint the desktop after docks move."""
    if not desktop_enabled():
        return
    try:
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x1000, None, None)
    except _SHELL_ERRORS:
        pass


HWND_BOTTOM = 1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_NOOWNERZORDER = 0x0200
SWP_SHOWWINDOW = 0x0040


def send_to_bottom(hwnd: int) -> bool:
    """Push a window to the bottom of the z-order, above the wallpaper only."""
    if not desktop_enabled() or not hwnd:
        return False
    try:
        flags = SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_NOOWNERZORDER | SWP_SHOWWINDOW
        return bool(ctypes.windll.user32.SetWindowPos(int(hwnd), HWND_BOTTOM, 0, 0, 0, 0, flags))
    except _SHELL_ERRORS:
        return False


def window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """Screen rectangle of a window handle."""
    if not desktop_enabled() or not hwnd:
        return None
    try:
        rect = wintypes.RECT()
        if ctypes.windll.user32.GetWindowRect(int(hwnd), ctypes.byref(rect)):
            return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
    except _SHELL_ERRORS:
        pass
    return None


if desktop_enabled():
    # Declare every Win64 prototype once at import, so no function depends on
    # being called after another one happened to run _declare_signatures() first.
    # This is what stops needs_reanchor() from comparing against truncated handles.
    _declare_signatures()

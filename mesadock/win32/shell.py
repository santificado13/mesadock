"""Shell integration: shortcut resolution, icons, autostart and clipboard paths.

Windows shortcuts are LNK files; MesaDock needs their target, arguments and the
icon Windows would draw for them. If the pywin32/pythoncom helpers are absent,
a small COM bridge via ctypes is used, and failing that the file's own icon.
"""
from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes as wintypes
import io
import os
import subprocess
from pathlib import Path

from . import is_windows

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".ico", ".webp")
SHORTCUT_SUFFIXES = (".lnk", ".url")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "MesaDock"


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]


# FOLDERID_Desktop from KnownFolders.h. Hard-coding the GUID is what lets us ask
# Windows for the real desktop folder instead of guessing a localized name.
_FOLDERID_DESKTOP = _GUID(
    0xB4BFCC3A, 0xDB2C, 0x424C,
    (ctypes.c_ubyte * 8)(0xB0, 0x29, 0x7F, 0xE9, 0x9A, 0x87, 0xC6, 0x41),
)


def known_desktop_dir() -> Path | None:
    """The desktop folder Windows itself reports, or None if it cannot be read.

    Guessing from Path.home()/"Desktop" is wrong on a machine whose desktop is
    redirected into OneDrive under a localized name ("Área de Trabalho"), which
    made restored shortcuts land in a folder the desktop does not show.
    """
    if not is_windows():
        return None
    try:
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        ole32 = ctypes.WinDLL("ole32", use_last_error=True)
        ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        ole32.CoTaskMemFree.restype = None
        shell32.SHGetKnownFolderPath.argtypes = [
            ctypes.POINTER(_GUID), ctypes.c_uint32, ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p)]
        shell32.SHGetKnownFolderPath.restype = ctypes.c_long
        pointer = ctypes.c_void_p()
        result = shell32.SHGetKnownFolderPath(
            ctypes.byref(_FOLDERID_DESKTOP), 0, None, ctypes.byref(pointer))
        if result != 0 or not pointer.value:
            return None
        try:
            text = ctypes.wstring_at(pointer.value)
        finally:
            ole32.CoTaskMemFree(pointer)
        return Path(text) if text else None
    except (OSError, AttributeError):
        return None


def is_shortcut(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SHORTCUT_SUFFIXES


def is_image(path: str | Path) -> bool:
    return Path(path).suffix.lower() in IMAGE_SUFFIXES


def is_url(text: str) -> bool:
    lowered = (text or "").strip().lower()
    return lowered.startswith(("http://", "https://", "mailto:", "ftp://"))


def classify(path_or_url: str) -> str:
    """Best guess at the item kind for a path or url."""
    text = (path_or_url or "").strip()
    if is_url(text):
        return "url"
    path = Path(text)
    if path.is_dir():
        return "folder"
    if is_shortcut(path):
        return "shortcut"
    return "file"


# --- .url files -----------------------------------------------------------
def read_url_file(path: str | Path) -> str:
    """Target URL stored in an Internet Shortcut (.url) file."""
    try:
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            if line.lower().startswith("url="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def write_url_file(path: str | Path, url: str) -> Path:
    """Create a minimal Internet Shortcut file pointing at url."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("[InternetShortcut]\nURL=" + url + "\n", encoding="utf-8")
    return target


# --- .lnk files -----------------------------------------------------------
def read_shortcut(path: str | Path) -> dict[str, str]:
    """Resolve a Windows shortcut to target, arguments, icon and working dir."""
    result = {"target": "", "args": "", "icon": "", "workdir": ""}
    shortcut = Path(path)
    if not shortcut.exists():
        return result
    if shortcut.suffix.lower() == ".url":
        result["target"] = read_url_file(shortcut)
        return result
    try:
        import win32com.client  # type: ignore

        shell = win32com.client.Dispatch("WScript.Shell")
        link = shell.CreateShortCut(str(shortcut))
        result["target"] = str(link.TargetPath or "")
        result["args"] = str(link.Arguments or "")
        result["icon"] = str(link.IconLocation or "")
        result["workdir"] = str(link.WorkingDirectory or "")
        return result
    except Exception:
        pass
    try:
        return _read_shortcut_via_vbs(shortcut)
    except Exception:
        return result


def _run_vbs(script: str) -> subprocess.CompletedProcess | None:
    """Run a short VBScript through cscript and return the finished process.

    The script is written to a temporary file as UTF-16 with a BOM: cscript does
    not read a script from stdin reliably (the "-" argument is treated as a file
    name and fails), and UTF-16 keeps non-ASCII paths such as "µTorrent.lnk"
    intact. The file is always removed.
    """
    import tempfile

    handle, path = tempfile.mkstemp(suffix=".vbs", prefix="mesadock_")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(b"\xff\xfe")
            stream.write(script.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-16-le"))
        return subprocess.run(
            ["cscript", "//nologo", "//E:vbscript", path],
            capture_output=True,
            timeout=15,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _vbs_quote(value: str) -> str:
    """Escape a value for a VBScript string literal."""
    return str(value).replace('"', '""')


def _read_shortcut_via_vbs(shortcut: Path) -> dict[str, str]:
    """Refatorado: Utiliza pylnk3 em memoria para evitar I/O no disco."""
    empty = {"target": "", "args": "", "icon": "", "workdir": ""}
    try:
        import pylnk3
        import io
        with open(shortcut, "rb") as f:
            data = f.read()
        lnk = pylnk3.parse(io.BytesIO(data))
        return {
            "target": lnk.path or "",
            "args": lnk.arguments or "",
            "icon": lnk.icon or "",
            "workdir": lnk.work_dir or ""
        }
    except Exception as exc:
        import logging
        logging.getLogger("mesadock").warning("Falha ao ler atalho %s: %s", shortcut, exc)
        return empty


def create_shortcut(link_path: str | Path, target: str, args: str = "", icon: str = "", workdir: str = "") -> bool:
    """Write a .lnk file pointing at target."""
    link = Path(link_path)
    try:
        link.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    script = (
        "Set s = CreateObject(\"WScript.Shell\")\n"
        "Set l = s.CreateShortcut(\"" + _vbs_quote(link) + "\")\n"
        "l.TargetPath = \"" + _vbs_quote(target) + "\"\n"
        "l.Arguments = \"" + _vbs_quote(args) + "\"\n"
        "l.WorkingDirectory = \"" + _vbs_quote(workdir) + "\"\n"
    )
    if icon:
        script += "l.IconLocation = \"" + _vbs_quote(icon) + "\"\n"
    script += "l.Save\n"
    completed = _run_vbs(script)
    return completed is not None and completed.returncode == 0 and link.exists()


# --- launching ------------------------------------------------------------
def launch(path: str, args: str = "") -> bool:
    """Open a file, folder, shortcut or url with its default handler."""
    try:
        if is_url(path):
            os.startfile(path)  # type: ignore[attr-defined]
        elif Path(path).exists():
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            return False
        return True
    except (OSError, AttributeError):
        try:
            subprocess.Popen(["cmd", "/c", "start", "", path], shell=False, creationflags=subprocess.CREATE_NO_WINDOW)
            return True
        except OSError:
            return False


def open_with(path: str, verb: str = "open") -> bool:
    """Invoke a shell verb (open, properties, print) on a path."""
    try:
        os.startfile(str(path), verb)  # type: ignore[attr-defined]
        return True
    except (OSError, AttributeError):
        return False


# --- icons ----------------------------------------------------------------
def _declare_icon_signatures() -> None:
    """Declare the Win64 prototypes for icon extraction.

    SHGetFileInfoW, the GDI calls in _hicon_to_image and DestroyIcon were called
    without argtypes/restype, so ctypes narrowed every handle and pointer to a
    32-bit C int on Win64. SHGetFileInfoW then wrote its SHFILEINFO struct to a
    bogus low address and the GDI calls worked on truncated handles: stack
    corruption the CRT caught as 0xc0000409 (BEX64) - the crash when adding a
    shortcut.
    """
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    shell32 = ctypes.windll.shell32

    shell32.SHGetFileInfoW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p, wintypes.UINT, wintypes.UINT,
    ]
    shell32.SHGetFileInfoW.restype = ctypes.c_size_t

    user32.DestroyIcon.argtypes = [wintypes.HANDLE]
    user32.DestroyIcon.restype = wintypes.BOOL
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HANDLE
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HANDLE]
    user32.ReleaseDC.restype = ctypes.c_int
    user32.DrawIconEx.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_int, wintypes.HANDLE,
        ctypes.c_int, ctypes.c_int, wintypes.UINT, wintypes.HANDLE, wintypes.UINT,
    ]
    user32.DrawIconEx.restype = wintypes.BOOL

    gdi32.CreateCompatibleDC.argtypes = [wintypes.HANDLE]
    gdi32.CreateCompatibleDC.restype = wintypes.HANDLE
    gdi32.CreateDIBSection.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, wintypes.UINT,
        ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD,
    ]
    gdi32.CreateDIBSection.restype = wintypes.HANDLE
    gdi32.SelectObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    gdi32.SelectObject.restype = wintypes.HANDLE
    gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.DeleteDC.argtypes = [wintypes.HANDLE]
    gdi32.DeleteDC.restype = wintypes.BOOL


def extract_icon_png(path: str, size: int = 64) -> bytes | None:
    """PNG bytes with the small icon Windows associates with a file."""
    if not is_windows():
        return None
    try:
        from PIL import Image

        if is_image(path) and not str(path).lower().endswith(".ico"):
            with Image.open(path) as image:
                return _png_bytes(image.convert("RGBA"), size)
        return extract_icon_with_shell(path, size) or extract_icon_via_powershell(path, size)
    except Exception:
        return None


class _GUID_STRUCT(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _iimagelist_iid():
    """IID_IImageList, used to ask shell32 for its large icon list."""
    guid = _GUID_STRUCT()
    guid.Data1 = 0x46EB5926
    guid.Data2 = 0x582E
    guid.Data3 = 0x4017
    for index, value in enumerate((0x9F, 0xDF, 0xE8, 0x99, 0x8D, 0xAA, 0x09, 0x50)):
        guid.Data4[index] = value
    return guid


def _imagelist_icon(image_list: int, index: int, flags: int) -> int:
    """HICON for one entry of an IImageList, via vtable slot 10 (GetIcon)."""
    try:
        vtable = ctypes.cast(image_list, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        get_icon = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_int,
                                      ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p))(vtable[10])
        icon = ctypes.c_void_p()
        if get_icon(ctypes.c_void_p(image_list), int(index), flags, ctypes.byref(icon)) != 0:
            return 0
        return int(icon.value or 0)
    except (AttributeError, OSError, TypeError, ValueError):
        return 0


def _com_release(pointer: int) -> None:
    """IUnknown::Release (vtable slot 2) for a COM interface pointer."""
    try:
        vtable = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
        release(ctypes.c_void_p(pointer))
    except (AttributeError, OSError, TypeError, ValueError):
        pass


def extract_icon_jumbo(path: str):
    """Best available icon for a file, at 256px when the shell provides one.

    SHGFI_LARGEICON only ever returns 32x32, which then had to be blown up to
    panel size and looked blurry. Asking the system image list for SHIL_JUMBO
    (256px) gives crisp artwork for shortcuts, and falls back to the smaller
    sizes when a file has no large icon.
    """
    if not is_windows():
        return None
    # Missing or empty paths make SHGetFileInfoW hand back a generic document
    # icon; callers need None so they can fall back to a placeholder.
    text = str(path or "").strip()
    if not text:
        return None
    if not text.lower().startswith(("http://", "https://")) and not Path(text).exists():
        return None
    _declare_icon_signatures()
    try:
        from PIL import Image

        SHGFI_SYSICONINDEX = 0x000004000
        SHGFI_ICON = 0x000000100
        SHIL_JUMBO = 0x4
        SHIL_EXTRALARGE = 0x2
        ILD_TRANSPARENT = 0x00000001

        class SHFILEINFO(ctypes.Structure):
            _fields_ = [
                ("hIcon", wintypes_handle()),
                ("iIcon", ctypes.c_int),
                ("dwAttributes", ctypes.c_uint32),
                ("szDisplayName", ctypes.c_wchar * 260),
                ("szTypeName", ctypes.c_wchar * 80),
            ]

        info = SHFILEINFO()
        shell32 = ctypes.windll.shell32
        # argtypes are mandatory here: without them ctypes passes the path as a
        # C int on 64-bit Windows and SHGetFileInfoW returns 0 for every file.
        shell32.SHGetFileInfoW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(SHFILEINFO),
            ctypes.c_uint, ctypes.c_uint,
        ]
        shell32.SHGetFileInfoW.restype = ctypes.c_size_t
        # SHGetFileInfoW can return 0 for shortcuts while still filling in a
        # usable iIcon, so its return value must not be treated as failure.
        shell32.SHGetFileInfoW(
            str(path), 0, ctypes.byref(info), ctypes.sizeof(info), SHGFI_SYSICONINDEX
        )

        get_image_list = shell32.SHGetImageList
        get_image_list.argtypes = [ctypes.c_int, ctypes.c_void_p,
                                   ctypes.POINTER(ctypes.c_void_p)]
        get_image_list.restype = ctypes.c_long
        iid = _iimagelist_iid()
        image_list = ctypes.c_void_p()
        if get_image_list(SHIL_JUMBO, ctypes.byref(iid), ctypes.byref(image_list)) != 0:
            return None
        if not image_list.value:
            return None
        try:
            hicon = _imagelist_icon(image_list.value, info.iIcon, ILD_TRANSPARENT)
        finally:
            _com_release(image_list.value)
        if not hicon:
            return None
        try:
            side = 256
            image = _hicon_to_image(hicon, side)
            return image
        finally:
            ctypes.windll.user32.DestroyIcon(hicon)
    except Exception:
        return None


def extract_icon_with_shell(path: str, size: int = 64) -> bytes | None:
    """Icon through the system image list (SHGetFileInfo)."""
    if not is_windows():
        return None
    _declare_icon_signatures()
    try:
        from PIL import Image

        class SHFILEINFO(ctypes.Structure):
            _fields_ = [
                ("hIcon", wintypes_handle()),
                ("iIcon", ctypes.c_int),
                ("dwAttributes", ctypes.c_uint32),
                ("szDisplayName", ctypes.c_wchar * 260),
                ("szTypeName", ctypes.c_wchar * 80),
            ]

        SHGFI_ICON = 0x000000100
        SHGFI_LARGEICON = 0x000000000
        info = SHFILEINFO()
        ctypes.windll.shell32.SHGetFileInfoW(
            str(path), 0, ctypes.byref(info), ctypes.sizeof(info), SHGFI_ICON | SHGFI_LARGEICON
        )
        if not info.hIcon:
            return None
        image = _hicon_to_image(info.hIcon, size)
        ctypes.windll.user32.DestroyIcon(info.hIcon)
        return _png_bytes(image, size) if image else None
    except Exception:
        return None


def wintypes_handle():
    from ctypes import wintypes

    return wintypes.HANDLE


def _hicon_to_image(handle: int, size: int):
    """Convert an HICON to a Pillow image through a 32-bit DIB section.

    The icon is drawn into a bitmap this function allocates, so the pixel
    format is always 32-bit BGRA no matter what the source icon used. Reading
    the icon's own mask/colour bitmaps directly is unsafe: masks are 1bpp and
    GetDIBits would overrun a fixed-size buffer (a hard access violation).
    """
    _declare_icon_signatures()
    try:
        from ctypes import wintypes

        from PIL import Image

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", wintypes.DWORD),
                ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD),
            ]

        class BITMAPINFO(ctypes.Structure):
            _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

        header = BITMAPINFOHEADER()
        header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        header.biWidth = size
        header.biHeight = -size  # top-down rows, matches Pillow's order
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = 0  # BI_RGB
        info = BITMAPINFO()
        info.bmiHeader = header

        hdc_screen = user32.GetDC(0)
        if not hdc_screen:
            return None
        memory = gdi32.CreateCompatibleDC(hdc_screen)
        bits = ctypes.c_void_p()
        bitmap = gdi32.CreateDIBSection(
            memory, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
        if not bitmap or not bits:
            gdi32.DeleteDC(memory)
            user32.ReleaseDC(0, hdc_screen)
            return None
        try:
            old = gdi32.SelectObject(memory, bitmap)
            # DI_NORMAL draws the mask and the colour bitmap together.
            user32.DrawIconEx(memory, 0, 0, int(handle), size, size, 0, None, 0x0003)
            gdi32.SelectObject(memory, old)
            raw = ctypes.string_at(bits, size * size * 4)
            image = Image.frombuffer("RGBA", (size, size), raw, "raw", "BGRA", 0, 1)
            return image.copy()
        finally:
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(memory)
            user32.ReleaseDC(0, hdc_screen)
    except Exception:
        return None


def extract_icon_via_powershell(path: str, size: int = 64) -> bytes | None:
    """Last-resort icon extraction through PowerShell plus the shell API."""
    if not is_windows():
        return None
    script = (
        "Add-Type -AssemblyName System.Drawing;"
        "$i=[System.Drawing.Icon]::ExtractAssociatedIcon('" + str(path).replace("'", "''") + "');"
        "$b=$i.ToBitmap();$b.Save([Console]::OpenStandardOutput(),[System.Drawing.Imaging.ImageFormat]::Png)"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            timeout=20,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if completed.returncode == 0 and completed.stdout:
            from PIL import Image

            with Image.open(io.BytesIO(completed.stdout)) as image:
                return _png_bytes(image.convert("RGBA"), size)
    except Exception:
        pass
    return None


def _png_bytes(image, size: int) -> bytes:
    from PIL import Image

    resized = image.resize((size, size), Image.LANCZOS) if image.size != (size, size) else image
    buffer = io.BytesIO()
    resized.save(buffer, format="PNG")
    return buffer.getvalue()


def icon_data_url(path: str, size: int = 64) -> str:
    """data: URL for an icon, or an empty string when extraction fails."""
    payload = extract_icon_png(path, size)
    if not payload:
        return ""
    return "data:image/png;base64," + base64.b64encode(payload).decode("ascii")


# --- autostart ------------------------------------------------------------
def _installed_executable() -> Path | None:
    """Path of the packaged MesaDock.exe when this machine has one installed.

    Checks ``MESADOCK_EXE`` (for a custom install folder) first, then the
    per-user locations under LOCALAPPDATA and %USERPROFILE%\\PROGRAMAS.
    """
    candidates = []
    override = os.environ.get("MESADOCK_EXE", "").strip()
    if override:
        candidates.append(Path(override))
    candidates += [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "MesaDock" / "MesaDock.exe",
        Path(os.environ.get("USERPROFILE", "")) / "PROGRAMAS" / "MesaDock" / "MesaDock.exe",
    ]
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None

def autostart_command() -> str:
    """Command line written to the Run key to start MesaDock at logon."""
    import sys

    if getattr(sys, "frozen", False):
        return "\"" + sys.executable + "\""
    # Running from source (dev or tests). Prefer the installed build when it is
    # present: writing the dev interpreter + __main__.py into the Run key made the
    # app start from a console window and break as soon as the folder moved. Every
    # dev run used to overwrite a correct entry with that fragile one.
    installed = _installed_executable()
    if installed is not None:
        return "\"" + str(installed) + "\""
    entry = Path(__file__).resolve().parent.parent / "__main__.py"
    return "\"" + sys.executable + "\" \"" + str(entry) + "\""


def autostart_enabled() -> bool:
    if not is_windows():
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, RUN_VALUE)
            return True
    except (OSError, ImportError):
        return False


def set_autostart(enabled: bool) -> bool:
    """Turn the per-user logon entry on or off. Returns the resulting state."""
    if not is_windows():
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, autostart_command())
            else:
                try:
                    winreg.DeleteValue(key, RUN_VALUE)
                except FileNotFoundError:
                    pass
        return autostart_enabled()
    except (OSError, ImportError):
        return autostart_enabled()

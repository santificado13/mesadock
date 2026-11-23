"""Per-pixel-alpha windows (UpdateLayeredWindow).

Tk can only make one exact colour see-through ("-transparentcolor"), which
leaves jagged edges: anti-aliased pixels blend into the key colour instead of
the wallpaper. A layered window updated with a 32-bit premultiplied bitmap has
real alpha per pixel, so rounded corners, soft shadows and translucent panels
blend with whatever is behind them.

Once a window is presented this way Windows shows only the bitmap: nothing Tk
draws inside it is visible, but its widgets still receive mouse input wherever
the bitmap is not fully transparent.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from . import is_windows

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
ULW_ALPHA = 0x02
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
GA_ROOT = 2


class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_byte), ("BlendFlags", ctypes.c_byte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_byte)]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


_declared = False


def _declare() -> None:
    global _declared
    if _declared:
        return
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    user32.SetWindowLongW.restype = ctypes.c_long
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int
    user32.UpdateLayeredWindow.argtypes = [
        wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(wintypes.SIZE),
        wintypes.HDC, ctypes.POINTER(wintypes.POINT), wintypes.COLORREF,
        ctypes.POINTER(_BLENDFUNCTION), wintypes.DWORD]
    user32.UpdateLayeredWindow.restype = wintypes.BOOL
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                       ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.DeleteDC.restype = wintypes.BOOL
    _declared = True


def available() -> bool:
    return is_windows()


def premultiplied_bgra(image) -> bytes:
    """Bytes of an RGBA Pillow image as premultiplied BGRA, the DIB layout."""
    from PIL import Image, ImageChops

    if image.mode != "RGBA":
        image = image.convert("RGBA")
    red, green, blue, alpha = image.split()
    red = ImageChops.multiply(red, alpha)
    green = ImageChops.multiply(green, alpha)
    blue = ImageChops.multiply(blue, alpha)
    return Image.merge("RGBA", (blue, green, red, alpha)).tobytes()


def present(hwnd: int, image, position: tuple[int, int] | None = None, opacity: float = 1.0) -> bool:
    """Show ``image`` (RGBA) as the whole content of the top-level window of ``hwnd``.

    ``position`` moves the window to that screen point in the same call; ``opacity``
    (0..1) scales the alpha of every pixel, which is how fades are animated.
    Returns False when the call failed, so the caller can fall back to Tk drawing.
    """
    if not is_windows() or not hwnd:
        return False
    try:
        _declare()
        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        top = user32.GetAncestor(hwnd, GA_ROOT) or hwnd
        style = user32.GetWindowLongW(top, GWL_EXSTYLE)
        if not style & WS_EX_LAYERED:
            user32.SetWindowLongW(top, GWL_EXSTYLE, style | WS_EX_LAYERED)

        width, height = image.size
        header = _BITMAPINFOHEADER()
        header.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        header.biWidth = width
        header.biHeight = -height  # top-down rows, matching Pillow
        header.biPlanes = 1
        header.biBitCount = 32
        pixels = premultiplied_bgra(image)

        screen_dc = user32.GetDC(None)
        if not screen_dc:
            return False
        memory_dc = bitmap = previous = None
        try:
            memory_dc = gdi32.CreateCompatibleDC(screen_dc)
            bits = ctypes.c_void_p()
            bitmap = gdi32.CreateDIBSection(screen_dc, ctypes.byref(header), 0, ctypes.byref(bits), None, 0)
            if not memory_dc or not bitmap or not bits:
                return False
            ctypes.memmove(bits, pixels, len(pixels))
            previous = gdi32.SelectObject(memory_dc, bitmap)
            blend = _BLENDFUNCTION(AC_SRC_OVER, 0, max(0, min(255, int(round(opacity * 255)))), AC_SRC_ALPHA)
            size = wintypes.SIZE(width, height)
            source = wintypes.POINT(0, 0)
            destination = ctypes.byref(wintypes.POINT(int(position[0]), int(position[1]))) if position else None
            ok = user32.UpdateLayeredWindow(top, screen_dc, destination, ctypes.byref(size), memory_dc,
                                            ctypes.byref(source), 0, ctypes.byref(blend), ULW_ALPHA)
            return bool(ok)
        finally:
            # A bitmap still selected into a DC cannot be deleted: restore first.
            if memory_dc and previous:
                gdi32.SelectObject(memory_dc, previous)
            if bitmap:
                gdi32.DeleteObject(bitmap)
            if memory_dc:
                gdi32.DeleteDC(memory_dc)
            user32.ReleaseDC(None, screen_dc)
    except (AttributeError, OSError, ValueError, ctypes.ArgumentError):
        return False

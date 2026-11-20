"""Colours, fonts and ttk styling shared by every window.

The look is a quiet, dark, modern Windows 11 adjacent surface: deep charcoal
panels, one accent per dock style, generous padding and no hard borders.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

# Magic colour that Tk renders as fully transparent (click-through) on Windows.
TRANSPARENT_KEY = "#06070a"

# Cohesive dark tokens
BG = "#0c0f17"
BG_ELEVATED = "#151b27"
BG_SIDEBAR = "#0f131d"
BG_INPUT = "#18202e"
BG_SURFACE = BG_ELEVATED
BG_SURFACE_ELEVATED = "#1c2434"

BORDER = "#243044"
BORDER_SOFT = "#1a2332"
BORDER_SUBTLE = BORDER_SOFT

TEXT = "#f0f4fc"
TEXT_PRIMARY = TEXT
TEXT_MUTED = "#94a3b8"
TEXT_SECONDARY = TEXT_MUTED
TEXT_DIM = "#55657e"
TEXT_DISABLED = TEXT_DIM

ACCENT = "#3b82f6"
ACCENT_BLUE = ACCENT
ACCENT_SOFT = "#1e3a66"
DANGER = "#f87171"
SUCCESS = "#34d399"

PANEL_LIGHT_BG = "#f4f6fa"
PANEL_LIGHT_BORDER = "#d5dbe5"
PANEL_LIGHT_TEXT = "#1a2230"

FONT_FAMILY = "Segoe UI"


def font(size: int = 10, weight: str = "normal") -> tuple[str, int, str]:
    return (FONT_FAMILY, size, weight)


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % (max(0, min(255, rgb[0])), max(0, min(255, rgb[1])), max(0, min(255, rgb[2])))


def blend(colour_a: str, colour_b: str, amount: float) -> str:
    """Mix two hex colours; amount 0 = a, 1 = b."""
    a = hex_to_rgb(colour_a)
    b = hex_to_rgb(colour_b)
    amount = max(0.0, min(1.0, amount))
    return rgb_to_hex(tuple(int(a[i] + (b[i] - a[i]) * amount) for i in range(3)))


def lighten(colour: str, amount: float = 0.12) -> str:
    return blend(colour, "#ffffff", amount)


def darken(colour: str, amount: float = 0.12) -> str:
    return blend(colour, "#000000", amount)


def rounded_rect(canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float, radius: float = 14, **kwargs) -> int:
    """Draw a rounded rectangle on a canvas (smooth polygon)."""
    radius = max(0, min(radius, (x2 - x1) / 2, (y2 - y1) / 2))
    points = [
        x1 + radius, y1,
        x2 - radius, y1,
        x2, y1,
        x2, y1 + radius,
        x2, y2 - radius,
        x2, y2,
        x2 - radius, y2,
        x1 + radius, y2,
        x1, y2,
        x1, y2 - radius,
        x1, y1 + radius,
        x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, splinesteps=24, **kwargs)


def apply_window_icon(window) -> None:
    """Give a Toplevel the MesaDock icon (silently ignored off Windows)."""
    try:
        from ..core import paths

        icon = paths.asset("mesadock_new.ico")
        if not icon.exists():
            icon = paths.asset("mesadock.ico")
        if icon.exists():
            window.iconbitmap(default=str(icon))
            return
    except Exception:
        pass
    try:
        from ..core import icons

        window.iconphoto(False, icons.dock_icon("grid", 64, item_count=0))
    except Exception:
        pass


def apply_ttk_theme(root) -> None:
    """Configure ttk widgets to match the dark MesaDock palette."""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    root.option_add("*Font", font(10))
    root.option_add("*TearOff", False)

    # Global defaults
    style.configure(".", background=BG, foreground=TEXT, fieldbackground=BG_INPUT, font=font(10))
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=BG_ELEVATED)
    style.configure("Sidebar.TFrame", background=BG_SIDEBAR)
    style.configure("Panel.TFrame", background=BG_ELEVATED)

    # Labels
    style.configure("TLabel", background=BG, foreground=TEXT, font=font(10))
    style.configure("Card.TLabel", background=BG_ELEVATED, foreground=TEXT)
    style.configure("Sidebar.TLabel", background=BG_SIDEBAR, foreground=TEXT)
    style.configure("Title.TLabel", background=BG, foreground=TEXT, font=font(18, "bold"))
    style.configure("H2.TLabel", background=BG, foreground=TEXT, font=font(12, "bold"))
    style.configure("CardTitle.TLabel", background=BG_ELEVATED, foreground=TEXT, font=font(11, "bold"))
    style.configure("Muted.TLabel", background=BG, foreground=TEXT_MUTED, font=font(9))
    style.configure("CardMuted.TLabel", background=BG_ELEVATED, foreground=TEXT_MUTED, font=font(9))
    style.configure("SidebarMuted.TLabel", background=BG_SIDEBAR, foreground=TEXT_MUTED, font=font(9))
    style.configure("Accent.TLabel", background=BG, foreground=ACCENT, font=font(9, "bold"))

    # Buttons
    style.configure("TButton", background=BG_INPUT, foreground=TEXT, borderwidth=0, relief="flat",
                    focusthickness=0, padding=(12, 6), font=font(10))
    style.map("TButton",
              background=[("active", lighten(BG_INPUT, 0.08)), ("disabled", BG_ELEVATED)],
              foreground=[("disabled", TEXT_DIM)])

    style.configure("Accent.TButton", background=ACCENT, foreground="#08111f", font=font(10, "bold"),
                    padding=(14, 6), borderwidth=0, relief="flat", focusthickness=0)
    style.map("Accent.TButton",
              background=[("active", lighten(ACCENT, 0.12)), ("disabled", ACCENT_SOFT)],
              foreground=[("disabled", TEXT_DIM)])

    style.configure("Ghost.TButton", background=BG, foreground=TEXT_MUTED, padding=(10, 6),
                    borderwidth=0, relief="flat", focusthickness=0)
    style.map("Ghost.TButton",
              background=[("active", BG_ELEVATED)],
              foreground=[("active", TEXT)])

    style.configure("Danger.TButton", background=BG_INPUT, foreground=DANGER, padding=(10, 6),
                    borderwidth=0, relief="flat", focusthickness=0)
    style.map("Danger.TButton",
              background=[("active", "#3a1d22")],
              foreground=[("active", lighten(DANGER, 0.1))])

    style.configure("SmallGhost.TButton", background=BG_ELEVATED, foreground=TEXT_MUTED,
                    padding=(6, 3), font=font(9), borderwidth=0, relief="flat", focusthickness=0)
    style.map("SmallGhost.TButton",
              background=[("active", lighten(BG_ELEVATED, 0.08))],
              foreground=[("active", TEXT)])

    # Checkbuttons & Radiobuttons
    style.configure("TCheckbutton", background=BG, foreground=TEXT, focuscolor=BG)
    style.map("TCheckbutton", background=[("active", BG)], foreground=[("active", ACCENT)])
    style.configure("Card.TCheckbutton", background=BG_ELEVATED, foreground=TEXT, focuscolor=BG_ELEVATED)
    style.map("Card.TCheckbutton", background=[("active", BG_ELEVATED)], foreground=[("active", ACCENT)])

    style.configure("TRadiobutton", background=BG, foreground=TEXT)
    style.configure("Card.TRadiobutton", background=BG_ELEVATED, foreground=TEXT)
    style.map("Card.TRadiobutton", background=[("active", BG_ELEVATED)])

    # Entry & Spinbox
    style.configure("TEntry", fieldbackground=BG_INPUT, foreground=TEXT, insertcolor=TEXT,
                    borderwidth=0, relief="flat", padding=(8, 7), font=font(10))
    style.configure("TSpinbox", fieldbackground=BG_INPUT, foreground=TEXT, arrowcolor=TEXT_MUTED,
                    borderwidth=0, relief="flat", padding=(6, 6))

    # Combobox (dark field and dark dropdown)
    style.configure("TCombobox", fieldbackground=BG_INPUT, background=BG_INPUT, foreground=TEXT,
                    arrowcolor=TEXT_MUTED, borderwidth=0, darkcolor=BORDER_SOFT,
                    lightcolor=BORDER_SOFT, bordercolor=BORDER_SOFT, padding=(8, 6), font=font(10))
    style.map("TCombobox",
              fieldbackground=[("readonly", BG_INPUT), ("active", lighten(BG_INPUT, 0.04))],
              foreground=[("readonly", TEXT)],
              selectbackground=[("readonly", BG_INPUT)],
              selectforeground=[("readonly", TEXT)])
    root.option_add("*TCombobox*Listbox.background", BG_INPUT)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT_SOFT)
    root.option_add("*TCombobox*Listbox.selectForeground", TEXT)
    root.option_add("*TCombobox*Listbox.borderWidth", 0)
    root.option_add("*TCombobox*Listbox.highlightThickness", 1)
    root.option_add("*TCombobox*Listbox.highlightColor", BORDER)
    root.option_add("*TCombobox*Listbox.font", font(10))

    # Scales
    style.configure("TScale", background=BG, troughcolor=BG_INPUT, bordercolor=BG_INPUT,
                    lightcolor=ACCENT, darkcolor=ACCENT)
    style.configure("Card.TScale", background=BG_ELEVATED, troughcolor=BG_INPUT)
    style.layout("Card.TScale", [
        ("Horizontal.Scale.trough", {"sticky": "nswe", "children": [
            ("Horizontal.Scale.slider", {"side": "left", "sticky": ""}),
        ]}),
    ])

    style.configure("TSeparator", background=BORDER_SOFT)

    # Treeview (rowheight 32, no hard borders, soft accent selection, discreet heading)
    style.configure("Treeview", background=BG_ELEVATED, fieldbackground=BG_ELEVATED, foreground=TEXT,
                    borderwidth=0, rowheight=32, font=font(10), bordercolor=BORDER_SOFT,
                    lightcolor=BG_ELEVATED, darkcolor=BG_ELEVATED)
    style.configure("Treeview.Heading", background=BG_SIDEBAR, foreground=TEXT_MUTED, borderwidth=0,
                    relief="flat", font=font(9, "bold"), padding=(10, 8))
    style.map("Treeview", background=[("selected", ACCENT_SOFT)], foreground=[("selected", TEXT)])
    style.map("Treeview.Heading", background=[("active", BG_ELEVATED)])

    # Notebook & Tabs (flat tabs, active tab with accent text)
    style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 0, 0, 0),
                    darkcolor=BG, lightcolor=BG, bordercolor=BORDER_SOFT)
    style.configure("TNotebook.Tab", background=BG, foreground=TEXT_MUTED, padding=(18, 9),
                    borderwidth=0, font=font(10), bordercolor=BG,
                    lightcolor=BG, darkcolor=BG)
    style.map("TNotebook.Tab",
              background=[("selected", BG_ELEVATED), ("active", lighten(BG, 0.04))],
              foreground=[("selected", ACCENT), ("active", TEXT)],
              bordercolor=[("selected", BORDER_SOFT), ("!selected", BG)],
              lightcolor=[("selected", BG_ELEVATED), ("!selected", BG)])

    # Thin dark Scrollbars
    for sb in ("Vertical.TScrollbar", "Horizontal.TScrollbar", "TScrollbar"):
        style.configure(sb, background="#2a3547", troughcolor=BG, borderwidth=0,
                        arrowcolor=TEXT_MUTED, darkcolor=BG, lightcolor=BG,
                        bordercolor=BG, gripcount=0, arrowsize=11)
        style.map(sb, background=[("active", "#3f4d66"), ("disabled", BG)])

    return style

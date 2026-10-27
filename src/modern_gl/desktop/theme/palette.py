"""Colors as tokens: the one palette and the themes that change some of its colors."""

from __future__ import annotations

from dataclasses import dataclass, fields

from modern_gl.i18n import N_


@dataclass
class Palette:
    """One object for the whole program: set_theme() changes it in place, so modules
    that imported P see the new colors."""

    window: str = "#FFFFFF"
    sidebar: str = "#F5F6F8"
    surface: str = "#FFFFFF"
    subtle: str = "#F7F8FA"  # hover, zebra, input wells
    hairline: str = "#E8EAED"
    text: str = "#1D2025"
    muted: str = "#535965"  # done rows: a bit quieter than the text (D86)
    secondary: str = "#6B7280"
    tertiary: str = "#A0A6AF"
    accent: str = "#2D6BE4"
    accent_hover: str = "#255DCB"
    accent_soft: str = "#E8F0FD"
    selection: str = "#E3EBFA"
    sidebar_selection: str = "#E2E6ED"
    green: str = "#2E9E62"
    green_soft: str = "#E6F5EC"
    amber: str = "#C98A1B"
    amber_soft: str = "#FCF3E1"
    red: str = "#DC4446"
    red_soft: str = "#FCE9E9"
    violet: str = "#7C5CD6"
    teal: str = "#1F9BA6"
    currency: str = "#0F6F78"  # amounts in a currency under their account: readable teal
    field: str = "#F1F3F5"  # input wells: visible on white, quiet
    field_hover: str = "#EBEDF0"
    header_text: str = "#8A919B"  # column captions: quiet but readable
    canvas: str = "#FFFFFF"  # behind pages ("craft": grey under white sheets)
    sheet_border: str = "transparent"
    sheet_padding: str = "0"  # a sheet keeps its rows off its rounded edge
    sidebar_hover: str = "#ECEEF2"
    scrollbar: str = "#D5D9DF"
    scrollbar_hover: str = "#BCC2CA"
    on_accent: str = "#FFFFFF"  # text on accent, red buttons and icon squares
    tooltip: str = "#1D2025"
    tooltip_text: str = "#FFFFFF"
    toast_action: str = "#8AB4F8"  # «Undo» on the dark toast (it has tooltip colors)


# name -> (title in the menu, the colors that differ from Palette)
THEMES: dict[str, tuple[str, dict[str, str]]] = {
    "things": (N_("Things — один белый лист"), {}),
    "craft": (
        N_("Craft — серый фон, белые листы"),
        {
            "window": "#F6F7F9",
            "canvas": "#F6F7F9",
            "sidebar": "#EEF0F3",
            "sidebar_selection": "#E1E4EA",
            "field": "#FFFFFF",
            "field_hover": "#FFFFFF",
            "sheet_border": "#E6E8EC",
            "sheet_padding": "0 6px",
        },
    ),
    # Popular editor palettes (catppuccin.com, rosepinetheme.com, nordtheme.com): their
    # own colors; soft tints are the color mixed into the background.
    "catppuccin_latte": (
        N_("Catppuccin Latte — тёплый кремовый"),
        {
            "window": "#EFF1F5",
            "canvas": "#EFF1F5",
            "surface": "#EFF1F5",
            "sidebar": "#E6E9EF",
            "sidebar_hover": "#DFE3EA",
            "sidebar_selection": "#DCE0E8",
            "subtle": "#E6E9EF",
            "hairline": "#DCE0E8",
            "field": "#E6E9EF",
            "field_hover": "#DCE0E8",
            "text": "#4C4F69",
            "muted": "#5C5F77",
            "secondary": "#6C6F85",
            "tertiary": "#9CA0B0",
            "header_text": "#8C8FA1",
            "accent": "#1E66F5",
            "accent_hover": "#1A57D1",
            "accent_soft": "#DCE5F8",
            "selection": "#D5DFF5",
            "green": "#40A02B",
            "green_soft": "#DDEBDB",
            "amber": "#DF8E1D",
            "amber_soft": "#F3E6D6",
            "red": "#D20F39",
            "red_soft": "#F3DADF",
            "violet": "#8839EF",
            "teal": "#179299",
            "currency": "#0F7A80",
            "scrollbar": "#CCD0DA",
            "scrollbar_hover": "#ACB0BE",
            "tooltip": "#4C4F69",
            "tooltip_text": "#EFF1F5",
        },
    ),
    "rose_pine_dawn": (
        N_("Rosé Pine Dawn — мягкий бежевый"),
        {
            "window": "#FAF4ED",
            "canvas": "#FAF4ED",
            "surface": "#FAF4ED",
            "sidebar": "#F2E9E1",
            "sidebar_hover": "#ECE2D9",
            "sidebar_selection": "#E4DBD5",
            "subtle": "#F4EDE8",
            "hairline": "#E8DFD8",
            "field": "#F2E9E1",
            "field_hover": "#ECE2D9",
            "text": "#575279",
            "muted": "#6E6A86",
            "secondary": "#797593",
            "tertiary": "#9893A5",
            "header_text": "#9893A5",
            "accent": "#286983",
            "accent_hover": "#215A71",
            "accent_soft": "#E0E6E4",
            "selection": "#DCE4E3",
            "green": "#56949F",
            "green_soft": "#E2EAE6",
            "amber": "#D7902A",
            "amber_soft": "#F7E8D3",
            "red": "#B4637A",
            "red_soft": "#F2E1DF",
            "violet": "#907AA9",
            "teal": "#56949F",
            "currency": "#3B7680",
            "scrollbar": "#DFDAD9",
            "scrollbar_hover": "#CECACD",
            "tooltip": "#575279",
            "tooltip_text": "#FAF4ED",
        },
    ),
    "nord_light": (
        N_("Nord — холодный серо-голубой"),
        {
            "window": "#ECEFF4",
            "canvas": "#ECEFF4",
            "surface": "#ECEFF4",
            "sidebar": "#E5E9F0",
            "sidebar_hover": "#DEE3EB",
            "sidebar_selection": "#D8DEE9",
            "subtle": "#E5E9F0",
            "hairline": "#D8DEE9",
            "field": "#E5E9F0",
            "field_hover": "#DEE3EB",
            "text": "#2E3440",
            "muted": "#434C5E",
            "secondary": "#4C566A",
            "tertiary": "#8A93A5",
            "header_text": "#7B8598",
            "accent": "#5E81AC",
            "accent_hover": "#50729C",
            "accent_soft": "#DCE3EE",
            "selection": "#D5DEEA",
            "green": "#6E9459",
            "green_soft": "#E0E8DE",
            "amber": "#C08A2E",
            "amber_soft": "#F0E8DA",
            "red": "#BF616A",
            "red_soft": "#F0DEE1",
            "violet": "#B48EAD",
            "teal": "#6FA3A2",
            "currency": "#46807F",
            "scrollbar": "#D8DEE9",
            "scrollbar_hover": "#B9C2D0",
            "tooltip": "#3B4252",
            "tooltip_text": "#ECEFF4",
        },
    ),
    "catppuccin_mocha": (
        N_("Catppuccin Mocha — тёмная"),
        {
            "window": "#1E1E2E",
            "canvas": "#1E1E2E",
            "surface": "#1E1E2E",
            "sidebar": "#181825",
            "sidebar_hover": "#232334",
            "sidebar_selection": "#313244",
            "subtle": "#262637",
            "hairline": "#313244",
            "field": "#292A3B",
            "field_hover": "#313244",
            "text": "#CDD6F4",
            "muted": "#AEB5D0",
            "secondary": "#A6ADC8",
            "tertiary": "#6C7086",
            "header_text": "#7F849C",
            "accent": "#89B4FA",
            "accent_hover": "#A4C4FB",
            "accent_soft": "#2B3450",
            "selection": "#323D5A",
            "on_accent": "#1E1E2E",
            "green": "#A6E3A1",
            "green_soft": "#2A3B33",
            "amber": "#F9E2AF",
            "amber_soft": "#3B3628",
            "red": "#F38BA8",
            "red_soft": "#43293A",
            "violet": "#CBA6F7",
            "teal": "#94E2D5",
            "currency": "#94E2D5",
            "scrollbar": "#45475A",
            "scrollbar_hover": "#585B70",
            "tooltip": "#313244",
            "tooltip_text": "#CDD6F4",
            "toast_action": "#89B4FA",
        },
    ),
}
# "As the system": the light or the dark theme, as the system is set (D86)
SYSTEM_THEME = "system"
SYSTEM_TITLE = N_("Как в системе — светлая или тёмная")
SYSTEM_PAIR = ("things", "catppuccin_mocha")  # (light, dark)
DEFAULT_THEME = SYSTEM_THEME
P = Palette()
_current = DEFAULT_THEME
_shown = SYSTEM_PAIR[0]


def set_theme(name: str, dark: bool = False) -> str:
    """Switch the palette to a theme (an unknown name: the default); returns its name.
    `dark` — the system is dark: «as the system» takes the dark theme.
    The look changes once apply() runs and the pages are built again."""
    global _current, _shown
    _current = name if name in THEMES or name == SYSTEM_THEME else DEFAULT_THEME
    _shown = SYSTEM_PAIR[dark] if _current == SYSTEM_THEME else _current
    base, changes = Palette(), THEMES[_shown][1]
    for f in fields(Palette):
        setattr(P, f.name, changes.get(f.name, getattr(base, f.name)))
    return _current


def current_theme() -> str:
    """The theme chosen (it may be «as the system»)."""
    return _current


def shown_theme() -> str:
    """The theme whose colors are on the screen."""
    return _shown

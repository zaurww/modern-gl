"""The style sheet: the whole look of the program in the current theme's colors."""

from __future__ import annotations

from modern_gl.desktop.theme.icons import _check_mark
from modern_gl.desktop.theme.palette import P


def stylesheet() -> str:
    """The whole look of the program, in the current theme's colors."""
    return _window_css() + _controls_css() + _tables_css() + _panels_css()


def _window_css() -> str:
    """The window, tooltips and the sidebar."""
    return f"""
* {{ outline: 0; }}
QMainWindow, QWidget#page {{ background: {P.canvas}; }}
QToolTip {{
    background: {P.tooltip}; color: {P.tooltip_text}; border: none; padding: 5px 8px;
    border-radius: 6px;
}}

/* Sidebar */
QWidget#sidebar {{ background: {P.sidebar}; border-right: 1px solid {P.hairline}; }}
QListWidget#nav {{ background: transparent; border: none; }}
QListWidget#nav::item {{
    color: {P.text}; padding: 6px 8px; margin: 1px 10px; border-radius: 7px;
}}
QListWidget#nav::item:hover {{ background: {P.sidebar_hover}; }}
QListWidget#nav::item:selected {{ background: {P.sidebar_selection}; color: {P.text}; }}
QListWidget#nav::item:disabled {{ color: {P.text}; background: transparent; }}
QPushButton#company {{
    text-align: left; padding: 10px 12px; margin: 14px 10px 8px 10px; border: none;
    border-radius: 8px; color: {P.text}; background: transparent;
}}
QPushButton#company {{ padding-right: 32px; }}
QPushButton#company:hover {{ background: {P.sidebar_hover}; }}
QPushButton#company::menu-indicator {{ image: none; }}
"""


def _controls_css() -> str:
    """Buttons, segments, tags and inputs."""
    return f"""
/* Buttons */
QPushButton {{
    background: {P.surface}; color: {P.text}; border: 1px solid {P.hairline};
    border-radius: 7px; padding: 6px 14px;
}}
QPushButton:hover {{ background: {P.subtle}; }}
QPushButton:disabled {{ color: {P.tertiary}; }}
QPushButton#primary {{
    background: {P.accent}; color: {P.on_accent}; border: 1px solid {P.accent}; font-weight: 600;
}}
QPushButton#primary:hover {{ background: {P.accent_hover}; }}
QPushButton#primary:disabled {{
    background: {P.accent_soft}; border-color: {P.accent_soft}; color: {P.surface};
}}
QPushButton#flat {{ background: transparent; border: none; color: {P.accent}; padding: 6px 8px; }}
QPushButton#flat:hover {{ background: {P.accent_soft}; }}
QPushButton#crumb {{  /* a step of a page's path: «Bank › ABB › 22.10» (D78) */
    background: transparent; border: none; color: {P.accent}; padding: 2px 4px 2px 0;
}}
QPushButton#crumb:hover {{ text-decoration: underline; }}
QPushButton#more {{
    background: transparent; border: none; color: {P.secondary}; padding: 6px 8px;
    border-radius: 7px;
}}
QPushButton#flatMenu {{
    background: transparent; border: none; color: {P.accent}; padding: 6px 28px 6px 8px;
}}
QPushButton#flatMenu:hover {{ background: {P.accent_soft}; }}
QPushButton#more:hover {{ background: {P.field}; color: {P.text}; }}
QPushButton#danger {{ background: transparent; border: none; color: {P.red}; padding: 6px 8px; }}
QPushButton#danger:hover {{ background: {P.red_soft}; }}
QPushButton#dangerSolid {{
    background: {P.red}; color: {P.on_accent}; border: 1px solid {P.red}; font-weight: 600;
}}
QPushButton#dangerSolid:disabled {{
    background: {P.red_soft}; border: 1px solid {P.red_soft}; color: {P.surface};
}}
/* a choice of two or three: Mədaxil | Məxaric */
QPushButton#segment {{
    background: {P.field}; border: none; border-radius: 7px; color: {P.secondary};
    padding: 6px 16px;
}}
QPushButton#segment:hover {{ background: {P.field_hover}; color: {P.text}; }}
QPushButton#segment:checked {{ background: {P.accent_soft}; color: {P.accent}; font-weight: 600; }}
/* a tag of an element: «Связанная сторона»; on — blue, off — quiet (D64) */
QPushButton#tag {{
    background: {P.field}; border: none; border-radius: 11px; color: {P.secondary};
    padding: 3px 12px;
}}
QPushButton#tag:hover {{ background: {P.field_hover}; color: {P.text}; }}
QPushButton#tag:checked {{ background: {P.accent_soft}; color: {P.accent}; }}

/* Inputs */
QLineEdit, QDateEdit, QComboBox {{
    background: {P.field}; border: 1px solid {P.sheet_border}; border-radius: 7px;
    padding: 5px 8px; color: {P.text}; selection-background-color: {P.accent};
}}
QLineEdit:hover, QDateEdit:hover, QComboBox:hover {{ background: {P.field_hover}; }}
QLineEdit:focus, QDateEdit:focus, QComboBox:focus {{
    background: {P.surface}; border: 1px solid {P.accent};
}}
QLineEdit#titleEdit {{
    background: transparent; border: none; padding: 0; color: {P.text};
}}
QLineEdit#search {{ padding-left: 10px; min-width: 320px; }}
QLineEdit[invalid="true"] {{ color: {P.red}; border: 1px solid {P.red}; }}
QComboBox::drop-down, QDateEdit::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {P.surface}; border: 1px solid {P.hairline}; border-radius: 8px;
    selection-background-color: {P.selection}; selection-color: {P.text}; padding: 4px;
}}
"""


def _tables_css() -> str:
    """Tables, lists, reports, check boxes and menus."""
    return f"""
/* Tables */
QTableView {{
    background: {P.surface}; border: 1px solid {P.sheet_border}; border-radius: 12px;
    gridline-color: transparent; padding: {P.sheet_padding};
    selection-background-color: {P.selection}; selection-color: {P.text};
}}
/* lists (journal, chart, directories…): no rule under each row, air and hover instead */
QTableView#list::item {{ border-bottom: 1px solid transparent; }}
QTableView::item {{ border-bottom: 1px solid {P.hairline}; padding: 0 8px; }}
QTableView::item:hover {{ background: {P.subtle}; }}
QTableView::item:selected {{ background: {P.selection}; color: {P.text}; }}
/* reports: no rules either; soft zebra rows (the model) and a clear hover */
QTableView#report::item {{ border-bottom: 1px solid transparent; }}
QTableView#report::item:hover {{ background: {P.accent_soft}; }}
QTableView#report::item:selected {{ background: {P.selection}; color: {P.text}; }}
QTableView QLineEdit {{
    background: {P.surface}; border: 1px solid {P.accent}; border-radius: 4px; padding: 0 6px;
}}
QHeaderView {{ background: {P.surface}; border: none; }}
QHeaderView::section {{
    background: {P.surface}; color: {P.header_text}; border: none;
    border-bottom: 1px solid {P.hairline}; padding: 6px 11px;  /* = cell padding + text margin */
}}
QHeaderView::section:vertical {{
    color: {P.tertiary}; border: none; border-bottom: 1px solid {P.hairline}; padding: 0 6px;
}}
QTableCornerButton::section {{ background: {P.surface}; border: none; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {P.scrollbar}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {P.scrollbar_hover}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {P.scrollbar}; border-radius: 3px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QListView#completer {{
    background: {P.surface}; border: 1px solid {P.hairline}; border-radius: 10px;
    padding: 4px; outline: 0;
}}
QListView#completer::item {{ padding: 6px 10px; border-radius: 6px; color: {P.text}; }}
QListView#completer::item:hover {{ background: {P.subtle}; }}
QListView#completer::item:selected {{ background: {P.selection}; color: {P.text}; }}
QCheckBox {{ color: {P.secondary}; spacing: 8px; }}
/* drawn here, not by the style: its box is "the background a bit darker" — lost on dark */
QCheckBox::indicator {{
    width: 14px; height: 14px; border: 1px solid {P.scrollbar_hover}; border-radius: 4px;
    background: {P.surface};
}}
QCheckBox::indicator:hover {{ border-color: {P.accent}; }}
QCheckBox::indicator:checked {{
    background: {P.accent}; border-color: {P.accent}; image: url({_check_mark(P.on_accent)});
}}
QCheckBox::indicator:disabled {{ background: {P.subtle}; border-color: {P.hairline}; }}
QCheckBox::indicator:checked:disabled {{ background: {P.accent_soft}; }}
"""


def _panels_css() -> str:
    """Folded lines, notes, the bank's panels and the toast."""
    return f"""
QDialog#palette {{
    background: {P.surface}; border: 1px solid {P.hairline}; border-radius: 12px;
}}
QLineEdit#paletteSearch {{
    background: transparent; border: none; padding: 8px 6px; font-size: 16px; color: {P.text};
}}
QListWidget#paletteList {{ background: transparent; border: none; }}
QListWidget#paletteList::item {{
    color: {P.text}; padding: 0 8px; border-radius: 7px;
}}
QListWidget#paletteList::item:disabled {{ color: {P.header_text}; padding-top: 6px; }}
QListWidget#paletteList::item:selected {{ background: {P.selection}; color: {P.text}; }}
QFrame#toast {{ background: {P.tooltip}; border-radius: 10px; }}
QLabel#toastText {{ color: {P.tooltip_text}; background: transparent; }}
QPushButton#toastAction {{
    background: transparent; border: none; color: {P.toast_action}; font-weight: 600;
    padding: 2px 6px;
}}
QPushButton#toastAction:hover {{ text-decoration: underline; }}
QMenu {{
    background: {P.surface}; border: 1px solid {P.hairline}; border-radius: 10px; padding: 6px;
}}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 6px; color: {P.text}; }}
QMenu::item:selected {{ background: {P.selection}; }}
QMenu::separator {{ height: 1px; background: {P.hairline}; margin: 4px 8px; }}

QStatusBar {{ background: {P.window}; color: {P.secondary}; border-top: 1px solid {P.hairline}; }}
QLabel#secondary {{ color: {P.secondary}; }}
QLabel#tertiary {{ color: {P.tertiary}; }}
QLabel#columnCaption {{ color: {P.header_text}; }}
QLabel#success {{ color: {P.green}; }}
QLabel#caution {{ color: {P.amber}; }}
QLabel#negative {{ color: {P.red}; }}
QFrame#hairline {{ background: {P.hairline}; border: none; }}
QFrame#homeLine:hover {{ background: {P.subtle}; border-radius: 6px; }}
QFrame#rule {{ background: {P.hairline}; border: none; }}
/* a form's lines folded into one: where the money goes */
QFrame#summary {{ background: {P.subtle}; border: none; border-radius: 8px; }}
QFrame#summary QLabel {{ background: transparent; }}
QLabel#error {{
    color: {P.red}; background: {P.red_soft}; border-radius: 7px; padding: 7px 10px;
}}
/* a bank statement agrees with the bank (D78) */
QLabel#reconciled {{
    color: {P.green}; background: {P.green_soft}; border-radius: 7px; padding: 7px 10px;
}}
/* something to look at, not an error: changes on the portal after a reconciliation */
QLabel#warning {{
    color: {P.text}; background: {P.amber_soft}; border-radius: 7px; padding: 7px 10px;
}}
QFrame#note {{ background: {P.accent_soft}; border: none; border-radius: 8px; }}
QFrame#card {{
    background: {P.surface}; border: 1px solid {P.hairline}; border-radius: 12px;
}}
QFrame#card QLabel {{ background: transparent; border: none; }}
QFrame#note QLabel {{ color: {P.text}; background: transparent; }}
QFrame#note QPushButton#flat:hover {{ background: {P.selection}; }}
/* the period with the mouse (D105): quiet cells, the chosen ones blue */
QFrame#periodWindow {{
    background: {P.surface}; border: 1px solid {P.hairline}; border-radius: 12px;
}}
QLabel#periodYear {{ color: {P.text}; font-weight: 600; }}
QPushButton#periodPreset, QPushButton#periodCell {{
    background: transparent; border: none; border-radius: 7px; color: {P.text};
    padding: 6px 12px;
}}
QPushButton#periodPreset {{ text-align: left; }}
QPushButton#periodPreset:hover, QPushButton#periodCell:hover {{ background: {P.field_hover}; }}
QPushButton#periodPreset:checked, QPushButton#periodCell:checked {{
    background: {P.accent_soft}; color: {P.accent}; font-weight: 600;
}}
"""

"""The page around a report: the sidebar, the header, the table's cells; its CSS and script.
Everything from a company file goes through `esc` (or `link`, `num`) — a memo is data."""

from __future__ import annotations

from html import escape
from urllib.parse import quote, urlencode

from modern_gl import i18n
from modern_gl.i18n import tr

# desktop/theme/palette.py, «things»; importing it would bring Qt (tests/test_web.py compares)
COLORS = {
    "window": "#FFFFFF",
    "sidebar": "#F5F6F8",
    "sidebar_selection": "#E2E6ED",
    "hairline": "#E8EAED",
    "text": "#1D2025",
    "muted": "#535965",
    "secondary": "#6B7280",
    "accent": "#2D6BE4",
    "green": "#2E9E62",
    "amber": "#C98A1B",
    "red": "#DC4446",
    "field": "#F1F3F5",
    "header_text": "#8A919B",
}

CSS = (
    ":root{"
    + "".join(f"--{name.replace('_', '-')}:{value};" for name, value in COLORS.items())
    + """}
*{box-sizing:border-box}
body{margin:0;background:var(--window);color:var(--text);font:14px/1.45 Inter,"Segoe UI",
  system-ui,sans-serif;display:flex;min-height:100vh}
a{color:inherit;text-decoration:none}
a:hover{color:var(--accent)}
nav{width:220px;flex:none;background:var(--sidebar);border-right:1px solid var(--hairline);
  padding:18px 10px}
nav .company{display:block;font-weight:600;padding:6px 10px 16px}
nav .item{display:block;padding:6px 10px;border-radius:7px;margin:1px 0}
nav .item.on{background:var(--sidebar-selection)}
nav .item:hover{color:var(--text);background:var(--sidebar-selection)}
main{flex:1;min-width:0;padding:28px 36px 48px}
h1{font-size:24px;line-height:1.25;font-weight:700;margin:0}
.sub{color:var(--secondary);margin:4px 0 18px}
form.bar{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-bottom:12px}
.bar input,.bar select{font:inherit;color:var(--text);background:var(--field);
  border:1px solid transparent;border-radius:7px;padding:5px 9px}
.bar input:focus,.bar select:focus{outline:none;background:var(--window);
  border-color:var(--accent)}
.bar .step{padding:5px 11px;border-radius:7px;background:var(--field)}
.bar .search{min-width:220px}
.check{margin:0 0 12px;color:var(--secondary)}
.check.ok{color:var(--green)}
.check.bad{color:var(--red)}
.wrap{overflow-x:auto}
table{border-collapse:collapse;font-variant-numeric:tabular-nums}
table.full{width:100%}
th{color:var(--header-text);font-weight:500;text-align:left;padding:4px 10px;white-space:nowrap}
th.group{text-align:center}
td{border:1px solid var(--hairline);padding:2px 10px;height:24px}
td.num,th.num{text-align:right;white-space:nowrap}
td.num{min-width:104px}
a.link{color:var(--accent)}
tr.group td{font-weight:600}
tr.sub td{color:var(--secondary)}
tr.done td{color:var(--muted)}
tr.total td{font-weight:700;height:28px;border-top:1px solid var(--text)}
.dot{color:var(--amber)}
.empty{color:var(--secondary);padding:48px 0;text-align:center}
.list a{display:block;padding:9px 12px;border-bottom:1px solid var(--hairline)}
.note{color:var(--secondary);margin-top:12px}
@media(max-width:720px){body{display:block}nav{width:auto;border-right:0;
  border-bottom:1px solid var(--hairline);padding:10px}nav .item{display:inline-block}
  nav .company{padding-bottom:6px}main{padding:18px 16px 32px}}
"""
)

SCRIPT = """document.querySelectorAll("form.bar [data-auto]").forEach(function (el) {
  el.addEventListener("change", function () { el.form.submit(); });
});
"""


def esc(text: object) -> str:
    return escape(str(text), quote=True)


def link(href: str, text: object, css: str = "") -> str:
    style = f' class="{css}"' if css else ""
    return f'<a href="{esc(href)}"{style}>{esc(text)}</a>'


def company_path(company: str, page_name: str, **query: object) -> str:
    """The address of a company's page; a name goes as one path segment."""
    tail = "?" + urlencode(query) if query else ""
    return f"/c/{quote(company, safe='')}/{page_name}{tail}"


def amount(text: str) -> str:
    """ "1234.50" as a report shows it: «1 234.50», a minus in brackets, a zero empty (D127).
    Works on the string: the amount stays exact."""
    negative = text.startswith("-")
    whole, _, cents = text.removeprefix("-").partition(".")
    if not whole.strip("0") and not cents.strip("0"):
        return ""
    groups = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    shown = " ".join([whole, *groups]) + (f".{cents}" if cents else "")
    return f"({shown})" if negative else shown


def num(text: str) -> str:
    return f'<td class="num">{esc(amount(text))}</td>'


def page(title: str, subtitle: str, body: str, side: str = "") -> str:
    return (
        f'<!doctype html><html lang="{esc(i18n.language())}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{esc(title)}</title><link rel="stylesheet" href="/style.css"></head><body>'
        f"{side}<main><h1>{esc(title)}</h1>"
        f'<p class="sub">{esc(subtitle)}</p>{body}</main>'
        '<script src="/app.js"></script></body></html>'
    )


def sidebar(company: str, current: str, many: bool, period: dict[str, str]) -> str:
    items = [("osv", tr("Оборотно-сальдовая ведомость")), ("journal", tr("Журнал"))]
    links = "".join(
        link(company_path(company, name, **period), text, "item on" if name == current else "item")
        for name, text in items
    )
    other = link("/", tr("Все компании"), "item") if many else ""
    return f"<nav>{link('/', company, 'company')}{links}{other}</nav>"

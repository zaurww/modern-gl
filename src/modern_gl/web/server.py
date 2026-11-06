"""uv run modern-gl-web [--data FOLDER] [--file X.gl …] [--lang az|ru] [--port N] [--no-browser]

The reports in a browser on this computer. The server listens on 127.0.0.1 only and answers
only by an address of this computer (a site cannot reach it through a name of its own);
nothing here writes. One thread reads: an SQLite connection stays where it was opened.
"""

from __future__ import annotations

import argparse
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from modern_gl import i18n
from modern_gl.application import queries
from modern_gl.assistant.companies import Companies
from modern_gl.assistant.server import workspace_from
from modern_gl.domain.company import STOCK_ONLY
from modern_gl.domain.errors import LedgerError, NotFoundError
from modern_gl.i18n import tr
from modern_gl.infrastructure.app_settings import read_settings
from modern_gl.infrastructure.backup import BackupError
from modern_gl.web import pages
from modern_gl.web.layout import CSS, SCRIPT, company_path

HTML = "text/html; charset=utf-8"
HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'self'; script-src 'self'; form-action 'self'; "
        "base-uri 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


@dataclass(frozen=True)
class Reply:
    status: int
    body: str = ""
    kind: str = HTML
    location: str = ""


class Site:
    """Answers an address with a page; knows nothing of sockets."""

    def __init__(self, companies: Companies) -> None:
        self.companies = companies

    def answer(self, target: str) -> Reply:
        address = urlsplit(target)
        query = {k: v[-1] for k, v in parse_qs(address.query).items()}
        parts = [unquote(p) for p in address.path.split("/") if p]
        try:
            return self._route(parts, query)
        except NotFoundError as e:
            return Reply(HTTPStatus.NOT_FOUND, pages.problem(str(e)))
        except (LedgerError, BackupError, ValueError) as e:
            return Reply(HTTPStatus.BAD_REQUEST, pages.problem(str(e)))

    def _route(self, parts: list[str], query: dict[str, str]) -> Reply:
        if parts == ["style.css"]:
            return Reply(HTTPStatus.OK, CSS, "text/css; charset=utf-8")
        if parts == ["app.js"]:
            return Reply(HTTPStatus.OK, SCRIPT, "text/javascript; charset=utf-8")
        names = [f.name for f in self.companies.files()]
        if not parts:
            if len(names) == 1:
                return Reply(HTTPStatus.FOUND, location=company_path(names[0], "osv"))
            return Reply(HTTPStatus.OK, pages.companies(names))
        if len(parts) >= 3 and parts[0] == "c":
            return Reply(HTTPStatus.OK, self._company_page(parts[1], parts[2:], query, names))
        raise NotFoundError(tr("Такой страницы нет"))

    def _company_page(
        self, name: str, rest: list[str], query: dict[str, str], names: list[str]
    ) -> str:
        conn, company_id = self.companies.open(name)
        if queries.company_mode(conn, company_id) == STOCK_ONLY:  # D90: no books shown
            raise ValueError(tr("Компания ведёт только склад — отчётов по книгам нет"))
        year = date.today().year
        view = pages.View(
            conn,
            company_id,
            queries.company_name(conn, company_id),
            len(names) > 1,
            pages.iso_date(query.get("from", ""), f"{year}-01-01"),
            pages.iso_date(query.get("to", ""), f"{year}-12-31"),
            pages.book_of(query.get("book", "")),
            queries.parallel_books(conn, company_id),
            query.get("q", ""),
        )
        match rest:
            case ["osv"]:
                return pages.trial_balance(view)
            case ["journal"]:
                return pages.journal(view)
            case ["card"] if query.get("account"):
                return pages.account_card(view, query["account"])
            case ["doc", number] if number.isdecimal():
                return pages.document(view, int(number))
        raise NotFoundError(tr("Такой страницы нет"))


def make_handler(site: Site, reader: ThreadPoolExecutor) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        timeout = 30  # a browser keeps spare connections open without asking anything

        def do_GET(self) -> None:
            port = self.connection.getsockname()[1]
            if self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
                self._send(Reply(HTTPStatus.FORBIDDEN, kind="text/plain"))
                return
            self._send(reader.submit(site.answer, self.path).result())

        def _send(self, reply: Reply) -> None:
            body = reply.body.encode("utf-8")
            self.send_response(reply.status)
            self.send_header("Content-Type", reply.kind)
            self.send_header("Content-Length", str(len(body)))
            for name, value in HEADERS.items():
                self.send_header(name, value)
            if reply.location:
                self.send_header("Location", reply.location)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            """Addresses hold account codes and company names: not printed."""

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Modern GL: the reports in a browser")
    parser.add_argument("--data", type=Path, help="folder of company files")
    parser.add_argument("--file", type=Path, action="append", default=[], help="a company file")
    parser.add_argument("--lang", choices=sorted(i18n.LANGUAGES))
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser")
    args = parser.parse_args()
    language = args.lang or read_settings().language
    i18n.set_language(language if language in i18n.LANGUAGES else i18n.DEFAULT)
    companies = Companies(workspace_from(args))
    reader = ThreadPoolExecutor(max_workers=1)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(Site(companies), reader))
    address = f"http://127.0.0.1:{server.server_address[1]}/"
    print(address, flush=True)  # noqa: T201 only the address: a console may lack «ı», «ə»
    if not args.no_browser:
        webbrowser.open(address)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        reader.submit(companies.close).result()
        reader.shutdown()


if __name__ == "__main__":
    main()

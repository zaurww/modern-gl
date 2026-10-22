"""Model Context Protocol over stdio — only what a server of tools needs (D83).

JSON-RPC 2.0, one message per line: initialize, ping, tools/list, tools/call.
A tool's own failure (a LedgerError, a wrong date) is a result with isError, so the model
reads the message and can try again; a broken request is a JSON-RPC error.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import BinaryIO

from modern_gl.domain.errors import LedgerError

VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")  # newest first
PARSE_ERROR, INVALID_REQUEST, NO_METHOD, INVALID_PARAMS = -32700, -32600, -32601, -32602


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    run: Callable[..., dict]
    properties: dict[str, dict] = field(default_factory=dict)  # JSON Schema of each argument
    required: tuple[str, ...] = ()

    def listed(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": {
                "type": "object",
                "properties": self.properties,
                "required": list(self.required),
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        }


class RequestError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


class Server:
    def __init__(self, name: str, version: str, tools: Sequence[Tool], about: str = "") -> None:
        self.info = {"name": name, "version": version}
        self.about = about  # instructions for the model: what the server is for
        self.tools = {t.name: t for t in tools}

    def serve(self, stdin: BinaryIO, stdout: BinaryIO) -> None:
        for line in stdin:
            if not line.strip():
                continue
            answer = self.handle_line(line)
            if answer is not None:
                stdout.write(json.dumps(answer, ensure_ascii=False).encode("utf-8") + b"\n")
                stdout.flush()

    def handle_line(self, line: bytes | str) -> dict | None:
        try:
            message = json.loads(line)
        except ValueError:
            return _error(None, PARSE_ERROR, "not JSON")
        if not isinstance(message, dict):
            return _error(None, INVALID_REQUEST, "a request is an object")
        return self.handle(message)

    def handle(self, message: dict) -> dict | None:
        """The answer to a request; None for a notification (no id) or an answer."""
        if "method" not in message:
            return None  # an answer from the client: we never ask, so nothing to match
        request_id = message.get("id")
        try:
            result = self._dispatch(message["method"], message.get("params") or {})
        except RequestError as e:
            return None if request_id is None else _error(request_id, e.code, str(e))
        if request_id is None:
            return None
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _dispatch(self, method: str, params: dict) -> dict:
        if method == "initialize":
            asked = params.get("protocolVersion")
            return {
                "protocolVersion": asked if asked in VERSIONS else VERSIONS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": self.info,
                "instructions": self.about,
            }
        if method == "tools/list":
            return {"tools": [t.listed() for t in self.tools.values()]}
        if method == "tools/call":
            return self._call(params)
        if method == "ping" or method.startswith("notifications/"):
            return {}
        raise RequestError(NO_METHOD, f"unknown method: {method}")

    def _call(self, params: dict) -> dict:
        tool = self.tools.get(params.get("name", ""))
        if tool is None:
            raise RequestError(INVALID_PARAMS, f"unknown tool: {params.get('name')}")
        arguments = params.get("arguments") or {}
        unknown = set(arguments) - set(tool.properties)
        missing = set(tool.required) - set(arguments)
        if unknown or missing:
            raise RequestError(
                INVALID_PARAMS, f"unknown {sorted(unknown)}, missing {sorted(missing)}"
            )
        try:
            result = tool.run(**arguments)
        except (LedgerError, ValueError) as e:
            return {"content": [{"type": "text", "text": str(e)}], "isError": True}
        text = json.dumps(result, ensure_ascii=False)
        return {"content": [{"type": "text", "text": text}], "structuredContent": result}


def _error(request_id: object, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

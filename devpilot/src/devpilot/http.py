"""Versioned request specification and strict cURL import. No shell execution."""

from __future__ import annotations

import base64
import re
import shlex
from dataclasses import asdict, dataclass, field
from urllib.parse import urlsplit

_FORBIDDEN_HEADERS = {"host", "content-length", "transfer-encoding", "connection", "upgrade", "proxy-authorization", "proxy-connection"}


@dataclass(frozen=True)
class RequestSpec:
    url: str
    method: str = "GET"
    headers: list[list[str]] = field(default_factory=list)
    body: str = ""
    version: str = "request.v1"

    def __post_init__(self):
        if not isinstance(self.url, str) or len(self.url) > 8192 or any(c.isspace() or ord(c) < 32 for c in self.url):
            raise ValueError("Invalid URL")
        try:
            url = urlsplit(self.url)
            port = url.port
        except ValueError:
            raise ValueError("Invalid URL") from None
        if url.scheme not in {"http", "https"} or not url.hostname or url.username is not None or url.password is not None or url.fragment or (port is not None and port == 0):
            raise ValueError("Only HTTP(S) URLs without embedded credentials or fragments are supported")
        if self.method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"} or self.version != "request.v1":
            raise ValueError("Unsupported request method or version")
        if not isinstance(self.body, str) or len(self.body.encode("utf-8")) > 262144:
            raise ValueError("Body exceeds 256 KiB")
        if not isinstance(self.headers, list) or len(self.headers) > 64:
            raise ValueError("At most 64 headers are supported")
        for pair in self.headers:
            if not isinstance(pair, list) or len(pair) != 2 or not all(isinstance(v, str) for v in pair):
                raise ValueError("Headers must be name/value pairs")
            name, value = pair
            if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name) or name.lower() in _FORBIDDEN_HEADERS or any(ord(c) < 32 or ord(c) > 126 for c in value) or len(value) > 8192:
                raise ValueError("Invalid or unsafe request header")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or set(data) - {"url", "method", "headers", "body", "version"}:
            raise ValueError("Invalid request specification")
        try:
            return cls(**data)
        except (TypeError, KeyError):
            raise ValueError("Invalid request specification") from None


def parse_curl(command: str) -> RequestSpec:
    if not isinstance(command, str) or len(command) > 300000 or "$" in command or chr(0) in command:
        raise ValueError("Unsupported shell expansion or command size")
    command = re.sub(r"(?:\\|\x60|\^)\r?\n", " ", command)
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        raise ValueError("Unbalanced cURL quoting") from None
    if not tokens or tokens.pop(0).lower() not in {"curl", "curl.exe"}:
        raise ValueError("Paste one complete curl command")
    url, method, body = None, None, ""
    headers = []
    has_body = False
    i = 0
    value_flags = {"-X", "--request", "-H", "--header", "-d", "--data", "--data-raw", "--data-binary", "--json", "--url", "-u", "--user"}
    while i < len(tokens):
        token = tokens[i]
        if token in {"-s", "-S", "-sS", "--silent", "--show-error", "--compressed", "-i", "--include", "-N", "--no-buffer"}:
            i += 1
            continue
        flag, equal, inline = token.partition("=")
        if flag in value_flags:
            if equal:
                value = inline
            else:
                i += 1
                if i >= len(tokens):
                    raise ValueError("A cURL option is missing its value")
                value = tokens[i]
            if flag in {"-X", "--request"}:
                method = value.upper()
            elif flag in {"-H", "--header"}:
                name, sep, content = value.partition(":")
                if not sep:
                    raise ValueError("Header must contain a colon")
                headers.append([name.strip(), content.strip()])
            elif flag in {"-u", "--user"}:
                headers.append(["Authorization", "Basic " + base64.b64encode(value.encode()).decode()])
            elif flag == "--url":
                if url is not None:
                    raise ValueError("Only one URL is supported")
                url = value
            else:
                if value.startswith("@") or has_body:
                    raise ValueError("File reads and multiple body options are not supported")
                body, has_body = value, True
                if flag == "--json":
                    headers.extend([["Content-Type", "application/json"], ["Accept", "application/json"]])
        elif not token.startswith("-") and url is None:
            url = token
        else:
            raise ValueError("Unsupported option or multiple commands; shell execution, files, redirects, proxies and insecure TLS are disabled")
        i += 1
    if url is None:
        raise ValueError("cURL URL is missing")
    if has_body and not any(h[0].lower() == "content-type" for h in headers):
        headers.append(["Content-Type", "application/x-www-form-urlencoded"])
    return RequestSpec(url=url, method=method or ("POST" if has_body else "GET"), headers=headers, body=body)

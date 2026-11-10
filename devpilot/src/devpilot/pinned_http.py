"""Pinned HTTPX transport mechanism, with explicit caller-owned DNS policy.

No default resolver, App/config/environment lookup, admission, budgets or retry.
A callback must approve ALL DNS answers and return one literal unscoped IP. This
mechanism alone does not authorize a send or make an exported runner safe.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Awaitable, Callable

import httpx

from devpilot.http import RequestSpec

_VERSION = "pinned-http.v1"


class EvaluationPolicyError(ValueError):
    """Request denied by outbound policy before transport dispatch."""


class PinnedHTTPTransport(httpx.AsyncBaseTransport):
    """One fixed origin, one fresh policy callback and at most one inner send.

    The resolver receives the validated, original-origin URL on EVERY request.
    It is responsible for host allowlists and checks of ALL resolved addresses;
    returning a literal IP is not proof of policy/consent. Host and TLS SNI remain
    the original origin while the connection destination becomes that IP.

    Clients must separately disable redirects/environment proxies and impose
    total deadlines. Durable admission/dispatch precedes calling this transport.
    Requests contain sensitive values: do not log or serialize them here.
    """

    version = _VERSION

    def __init__(self, url: str, resolver: Callable[[RequestSpec], Awaitable[str]], *, version: str = _VERSION):
        if version != _VERSION or not callable(resolver):
            raise ValueError("Invalid pinned HTTP transport")
        RequestSpec(url=url)
        self.url = httpx.URL(url)
        self._resolver = resolver
        self.inner = httpx.AsyncHTTPTransport(verify=True, trust_env=False, retries=0)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        spec = RequestSpec(url=str(request.url))
        if (request.url.scheme, request.url.host, request.url.port) != (self.url.scheme, self.url.host, self.url.port):
            raise EvaluationPolicyError("Evaluation request changed destination")
        ip = await self._resolver(spec)
        # Never hand a hostname back to HTTPX for a second, unchecked DNS lookup.
        # Scopes are not part of the supported portable literal-address contract.
        try:
            if type(ip) is not str or "%" in ip:
                raise ValueError
            ipaddress.ip_address(ip)
        except ValueError:
            raise EvaluationPolicyError("Invalid resolved destination") from None
        request.headers["host"] = request.url.netloc.decode("ascii")
        request.extensions["sni_hostname"] = request.url.host
        request.url = request.url.copy_with(host=ip)
        return await self.inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self.inner.aclose()

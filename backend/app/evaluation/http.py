"""Bounded, DNS-pinned outbound requests. No redirects, proxy env or TLS bypass."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from urllib.parse import urlsplit

import httpx
from devpilot.http import RequestSpec


async def resolve_destination(spec: RequestSpec, config) -> str:
    policy = getattr(config, "evaluation_http", {})
    parts = urlsplit(spec.url)
    host = parts.hostname.lower()
    if host not in policy.get("allowed_hosts", []):
        raise ValueError("Destination host is not approved by the operator (evaluation_http.allowed_hosts)")
    addresses = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM), timeout=5)
    ips = list(dict.fromkeys(row[4][0] for row in addresses))
    if not ips:
        raise ValueError("Destination DNS resolution failed")
    for value in ips:
        ip = ipaddress.ip_address(value)
        if ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved or (not ip.is_global and not policy.get("allow_private", False)):
            raise ValueError("Destination address is not permitted by outbound policy")
    return ips[0]


def component_request_spec(component: dict, params: dict) -> RequestSpec:
    """Validate caller-controlled URL/headers with the same contract as cURL import."""
    headers = params.get("headers", {})
    if not isinstance(headers, dict):
        raise ValueError("Request headers must be an object")
    return RequestSpec(url=component["api_url"], method="POST", headers=[[name, value] for name, value in headers.items()])


class PinnedEvaluationTransport(httpx.AsyncBaseTransport):
    """One origin per client; re-resolve and pin every outbound request, including queued runs."""

    def __init__(self, config, url: str):
        RequestSpec(url=url)
        self.config, self.url = config, httpx.URL(url)
        self.inner = httpx.AsyncHTTPTransport(verify=True, trust_env=False, retries=0)

    async def handle_async_request(self, request):
        spec = RequestSpec(url=str(request.url))
        if (request.url.scheme, request.url.host, request.url.port) != (self.url.scheme, self.url.host, self.url.port):
            raise ValueError("Evaluation request changed destination")
        ip = await resolve_destination(spec, self.config)
        request.headers["host"] = request.url.netloc.decode("ascii")
        request.extensions["sni_hostname"] = request.url.host
        request.url = request.url.copy_with(host=ip)
        return await self.inner.handle_async_request(request)

    async def aclose(self):
        await self.inner.aclose()


def evaluation_client(config, url: str, *, timeout_seconds: float = 30) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=PinnedEvaluationTransport(config, url), trust_env=False, follow_redirects=False, timeout=timeout_seconds)


async def send_request(spec: RequestSpec, config) -> dict:
    headers = list(map(tuple, spec.headers))
    started = time.perf_counter()
    async with asyncio.timeout(35):
        async with evaluation_client(config, spec.url, timeout_seconds=30) as client:
            async with client.stream(spec.method, spec.url, headers=headers, content=spec.body.encode("utf-8")) as response:
                chunks = bytearray()
                truncated = False
                async for chunk in response.aiter_bytes():
                    remaining = 1048576 - len(chunks)
                    chunks.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        truncated = True
                        break
                safe_headers = [[k, "[redacted]" if k.lower() in {"set-cookie", "authorization", "proxy-authenticate"} else v] for k, v in response.headers.multi_items()]
                text = chunks.decode("utf-8", errors="replace")
                for name, value in spec.headers:
                    if name.lower() in {"authorization", "cookie", "x-api-key", "api-key"} and value:
                        text = text.replace(value, "[redacted]")
                        if name.lower() == "authorization":
                            text = text.replace(value.split(" ", 1)[-1], "[redacted]")
                return {"status": response.status_code, "headers": safe_headers, "body": text, "elapsed_ms": round((time.perf_counter() - started) * 1000, 2), "size_bytes": len(chunks), "truncated": truncated, "redirects_followed": False}

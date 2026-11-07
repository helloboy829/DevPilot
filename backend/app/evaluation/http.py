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


async def send_request(spec: RequestSpec, config) -> dict:
    ip = await resolve_destination(spec, config)
    original = httpx.URL(spec.url)
    pinned = original.copy_with(host=ip)
    headers = list(map(tuple, spec.headers)) + [("Host", original.netloc.decode("ascii"))]
    started = time.perf_counter()
    async with asyncio.timeout(35):
        async with httpx.AsyncClient(verify=True, trust_env=False, follow_redirects=False, timeout=30) as client:
            async with client.stream(spec.method, pinned, headers=headers, content=spec.body.encode("utf-8"), extensions={"sni_hostname": original.host}) as response:
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

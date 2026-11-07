"""AI 组件协议适配层（transports）。

按 ``transport`` 类型分发到对应的请求构造 / 响应解析，全部走 ``httpx.AsyncClient``。

遵循 skill 的 code-conventions：

- ``trust_env=False``（不走环境代理）、``verify=True``（管理员部署受信任 CA，不能跳过证书校验）。
- **业务失败 ≠ HTTP 失败**：Dify 返回 200 但 ``data.status in (failed, stopped)``
  或 ``error`` 非空即失败；OpenAI 兼容端点返回 200 但 body 只有 ``error`` 也算失败。
- **TTFT = 首个用户可见 answer 分片**，不是首个 HTTP 字节，也不是首个 SSE 事件。
- 流式无 ``usage`` 时按文本估算 token（``estimate_tokens``，CJK 感知）。

本模块只依赖 httpx，不依赖 deerflow，可独立单测。
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx

#: 支持流式（SSE）的 transport。http_post 的泛化端点不假设 SSE，MVP 走阻塞。
STREAMING_TRANSPORTS: frozenset[str] = frozenset({"openai_chat", "dify_chat", "dify_workflow"})

#: Dify 的「业务失败」状态（HTTP 200 但业务没跑成）。
_DIFY_FAILED_STATUSES: frozenset[str] = frozenset({"failed", "stopped"})


def estimate_tokens(text: str) -> int:
    """无 ``usage`` 时按文本估算 token（CJK 感知）。

    CJK 字符按 ~1 token 计，其余按 ~4 字符/token 计；空文本返回 0。
    与 skill 的「流式无 usage 按文本估 token」口径一致。
    """
    if not text:
        return 0
    cjk = sum(1 for c in text if "一" <= c <= "鿿")
    other = len(text) - cjk
    return max(1, cjk + other // 4)


def dify_business_failed(data: Mapping[str, Any]) -> bool:
    """Dify 业务失败判定：``status in (failed, stopped)`` 或 ``error`` 非空。"""
    status = data.get("status")
    if status in _DIFY_FAILED_STATUSES:
        return True
    error = data.get("error")
    return error not in (None, "", False, {})


@dataclass
class TransportConfig:
    """被测组件的协议配置（来自组件注册表的扁平字段）。"""

    transport: str
    api_url: str
    api_token: str | None = None
    response_mode: str = "blocking"  # blocking | streaming
    headers: dict[str, str] = field(default_factory=dict)
    model: str | None = None  # openai_chat 的 model 名
    timeout_seconds: float = 30.0


@dataclass
class TransportResult:
    """一次调用的归一化结果，供 effect / perf 两层共用。"""

    transport: str
    success: bool  # 业务成功（含 HTTP + 业务失败双重判定）
    http_status: int | None = None
    latency_ms: float = 0.0
    ttft_ms: float | None = None  # 首个用户可见分片耗时（阻塞模式为 None）
    text: str = ""  # 用户可见答案文本
    total_tokens: int = 0  # prompt + completion；无 usage 时按 text 估算
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    error: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)  # 完整原始响应，供落盘/重评


def _build_client(timeout_seconds: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        trust_env=False,
        verify=True,
        timeout=httpx.Timeout(timeout_seconds),
    )


def _auth_headers(config: TransportConfig) -> dict[str, str]:
    headers = dict(config.headers)
    if config.api_token:
        # 兼容 OpenAI 风格 Bearer 与 Dify 风格 Authorization，二者同形。
        if not any(k.lower() == "authorization" for k in headers):
            headers["Authorization"] = f"Bearer {config.api_token}"
    headers.setdefault("Content-Type", "application/json")
    return headers


async def call_transport(
    config: TransportConfig,
    payload: Mapping[str, Any],
    *,
    client: httpx.AsyncClient | None = None,
    stream: bool | None = None,
) -> TransportResult:
    """按 transport 分发一次调用并归一化结果。

    ``stream`` 为 None 时按 ``config.response_mode`` 决定；显式传 True/False 覆盖。
    """
    if stream is None:
        stream = config.response_mode == "streaming" and config.transport in STREAMING_TRANSPORTS

    own_client = client is None
    if own_client:
        client = _build_client(config.timeout_seconds)

    try:
        if config.transport == "openai_chat":
            result = await _call_openai(client, config, payload, stream=stream)
        elif config.transport == "dify_chat":
            result = await _call_dify(client, config, payload, stream=stream, is_workflow=False)
        elif config.transport == "dify_workflow":
            result = await _call_dify(client, config, payload, stream=stream, is_workflow=True)
        elif config.transport == "http_post":
            result = await _call_http_post(client, config, payload)
        else:
            result = TransportResult(
                transport=config.transport,
                success=False,
                error=f"不支持的 transport: {config.transport}",
            )
    finally:
        if own_client and client is not None:
            await client.aclose()

    return result


def _now_ms(start: float) -> float:
    return (time.monotonic() - start) * 1000.0


# ── OpenAI Chat ─────────────────────────────────────────────────────────


def _openai_body(config: TransportConfig, payload: Mapping[str, Any], stream: bool) -> dict[str, Any]:
    body: dict[str, Any] = dict(payload)
    body["stream"] = stream
    if stream:
        body.setdefault("stream_options", {"include_usage": True})
    if config.model and "model" not in body:
        body["model"] = config.model
    return body


def _openai_text(data: Mapping[str, Any]) -> str:
    """从 OpenAI chat 响应提取答案文本。"""
    parts: list[str] = []
    for choice in data.get("choices") or []:
        if not isinstance(choice, Mapping):
            continue
        message = choice.get("message") or choice.get("delta") or {}
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
    return "".join(parts)


def _openai_error(data: Mapping[str, Any]) -> str | None:
    """OpenAI 兼容端点的错误：2xx 但无 choices 且带 error。"""
    if data.get("choices") is None and isinstance(data.get("error"), Mapping):
        return json.dumps(data["error"], ensure_ascii=False)
    if data.get("choices") is None and isinstance(data.get("error"), str) and data["error"]:
        return data["error"]
    return None


async def _call_openai(
    client: httpx.AsyncClient,
    config: TransportConfig,
    payload: Mapping[str, Any],
    *,
    stream: bool,
) -> TransportResult:
    url = config.api_url
    headers = _auth_headers(config)
    body = _openai_body(config, payload, stream)
    start = time.monotonic()

    if stream:
        chunks: list[str] = []
        usage: dict[str, Any] | None = None
        ttft: float | None = None
        http_status: int | None = None
        async with client.stream("POST", url, json=body, headers=headers) as resp:
            http_status = resp.status_code
            async for data_str in _iter_sse_data(resp):
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                if not isinstance(chunk, Mapping):
                    continue
                if isinstance(chunk.get("usage"), Mapping):
                    usage = dict(chunk["usage"])
                for choice in chunk.get("choices") or []:
                    if not isinstance(choice, Mapping):
                        continue
                    delta = ((choice.get("delta") or {}).get("content")) or ""
                    if delta:
                        if ttft is None:
                            ttft = _now_ms(start)
                        chunks.append(delta)
        text = "".join(chunks)
        return _finish_result(config, text, usage=usage, ttft_ms=ttft, start=start, http_status=http_status, raw={"stream": True, "text": text, "usage": usage})

    try:
        resp = await client.post(url, json=body, headers=headers)
    except httpx.RequestError as exc:
        return _request_error(config, exc, start)

    data = _safe_json(resp)
    error = _openai_error(data) if isinstance(data, dict) else None
    if resp.status_code >= 400:
        error = error or f"HTTP {resp.status_code}"
    text = _openai_text(data) if isinstance(data, dict) else ""
    usage = data.get("usage") if isinstance(data, dict) and isinstance(data.get("usage"), Mapping) else None
    return _finish_result(config, text, usage=usage, ttft_ms=None, start=start, http_status=resp.status_code, error=error, raw=data)


# ── Dify Chat / Workflow ────────────────────────────────────────────────


def _dify_body(
    config: TransportConfig,
    payload: Mapping[str, Any],
    stream: bool,
    *,
    is_workflow: bool,
) -> dict[str, Any]:
    body: dict[str, Any] = {"response_mode": "streaming" if stream else "blocking"}
    if is_workflow:
        body["inputs"] = payload.get("inputs") or {}
    else:
        body["inputs"] = payload.get("inputs") or {}
        body["query"] = payload.get("query") or ""
        if payload.get("conversation_id"):
            body["conversation_id"] = payload["conversation_id"]
    if payload.get("user"):
        body["user"] = payload["user"]
    return body


def _dify_usage(data: Mapping[str, Any]) -> dict[str, Any] | None:
    """从 Dify 响应的 metadata.usage / 顶层 usage 提取 token 用量。"""
    for container in (data.get("metadata"), data):
        if isinstance(container, Mapping) and isinstance(container.get("usage"), Mapping):
            return dict(container["usage"])
    return None


def _usage_to_tokens(usage: Mapping[str, Any] | None) -> tuple[int | None, int | None, int | None]:
    if not usage:
        return None, None, None
    prompt = _as_int(usage.get("prompt_tokens"))
    completion = _as_int(usage.get("completion_tokens"))
    total = _as_int(usage.get("total_tokens"))
    if total is None and prompt is not None and completion is not None:
        total = prompt + completion
    return prompt, completion, total


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


async def _call_dify(
    client: httpx.AsyncClient,
    config: TransportConfig,
    payload: Mapping[str, Any],
    *,
    stream: bool,
    is_workflow: bool,
) -> TransportResult:
    url = config.api_url
    headers = _auth_headers(config)
    body = _dify_body(config, payload, stream, is_workflow=is_workflow)
    start = time.monotonic()

    if stream:
        chunks: list[str] = []
        usage: dict[str, Any] | None = None
        error: str | None = None
        ttft: float | None = None
        http_status: int | None = None
        async with client.stream("POST", url, json=body, headers=headers) as resp:
            http_status = resp.status_code
            async for data_str in _iter_sse_data(resp):
                try:
                    evt = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                if not isinstance(evt, Mapping):
                    continue
                if evt.get("event") == "error":
                    error = str(evt.get("message") or evt.get("code") or "Dify stream error")
                    continue
                if is_workflow and evt.get("event") in ("workflow_finished", "workflow_failed"):
                    inner = evt.get("data") or {}
                    if dify_business_failed(inner):
                        error = error or str(inner.get("error") or inner.get("status"))
                answer = evt.get("answer")
                if isinstance(answer, str) and answer:
                    if ttft is None:
                        ttft = _now_ms(start)
                    chunks.append(answer)
                if evt.get("event") == "message_end":
                    usage = _dify_usage(evt) or usage
        text = "".join(chunks)
        return _finish_result(config, text, usage=usage, ttft_ms=ttft, start=start, http_status=http_status, error=error, raw={"stream": True, "text": text, "usage": usage, "error": error})

    try:
        resp = await client.post(url, json=body, headers=headers)
    except httpx.RequestError as exc:
        return _request_error(config, exc, start)

    data = _safe_json(resp)
    if not isinstance(data, dict):
        return _finish_result(config, "", usage=None, ttft_ms=None, start=start, http_status=resp.status_code, error=f"非 JSON 响应: {str(data)[:200]}", raw=data)

    if is_workflow:
        inner = data.get("data") if isinstance(data.get("data"), Mapping) else {}
        failed = dify_business_failed(inner)
        text = _stringify_outputs(inner.get("outputs")) if not failed else ""
        usage = _usage_to_tokens({"total_tokens": inner.get("total_tokens")})
        error = str(inner.get("error")) if failed and inner.get("error") not in (None, "", False, {}) else None
        return _finish_result(config, text, usage={"total_tokens": usage[2]} if usage[2] is not None else None, ttft_ms=None, start=start, http_status=resp.status_code, error=error, raw=data)

    failed = dify_business_failed(data)
    text = data.get("answer") if isinstance(data.get("answer"), str) and not failed else ""
    usage = _dify_usage(data)
    error = str(data.get("error")) if failed and data.get("error") not in (None, "", False, {}) else (data.get("status") if failed else None)
    return _finish_result(config, text, usage=usage, ttft_ms=None, start=start, http_status=resp.status_code, error=error, raw=data)


def _stringify_outputs(outputs: Any) -> str:
    """把 workflow 的 outputs 归一化成可读文本。"""
    if isinstance(outputs, str):
        return outputs
    if outputs is None:
        return ""
    return json.dumps(outputs, ensure_ascii=False)


# ── 通用 HTTP POST ──────────────────────────────────────────────────────


async def _call_http_post(
    client: httpx.AsyncClient,
    config: TransportConfig,
    payload: Mapping[str, Any],
) -> TransportResult:
    url = config.api_url
    headers = _auth_headers(config)
    start = time.monotonic()
    try:
        resp = await client.post(url, json=dict(payload), headers=headers)
    except httpx.RequestError as exc:
        return _request_error(config, exc, start)

    data = _safe_json(resp)
    text = _stringify_outputs(data) if not isinstance(data, str) else data
    error = None
    if resp.status_code >= 400:
        error = f"HTTP {resp.status_code}"
    return _finish_result(config, text, usage=None, ttft_ms=None, start=start, http_status=resp.status_code, error=error, raw=data)


# ── 通用工具 ────────────────────────────────────────────────────────────


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except (json.JSONDecodeError, ValueError):
        return resp.text


def _finish_result(
    config: TransportConfig,
    text: str,
    *,
    usage: Mapping[str, Any] | None,
    ttft_ms: float | None,
    start: float,
    http_status: int | None,
    error: str | None = None,
    raw: Any,
) -> TransportResult:
    prompt, completion, total = _usage_to_tokens(usage)
    if total is None:
        total = estimate_tokens(text)
    success = error is None and (http_status is None or http_status < 400)
    return TransportResult(
        transport=config.transport,
        success=success,
        http_status=http_status,
        latency_ms=_now_ms(start),
        ttft_ms=ttft_ms,
        text=text,
        total_tokens=total,
        prompt_tokens=prompt,
        completion_tokens=completion,
        error=error,
        raw=raw if raw is not None else {},
    )


def _request_error(config: TransportConfig, exc: httpx.RequestError, start: float) -> TransportResult:
    return TransportResult(
        transport=config.transport,
        success=False,
        latency_ms=_now_ms(start),
        error=f"{type(exc).__name__}: {exc}",
    )


async def _iter_sse_data(response: httpx.Response) -> AsyncIterator[str]:
    """从 SSE 响应逐行解析 ``data:`` 载荷。"""
    async for line in response.aiter_lines():
        line = line.strip()
        if not line or line.startswith(":"):
            continue
        if line.startswith("data:"):
            yield line[len("data:") :].strip()


__all__ = [
    "STREAMING_TRANSPORTS",
    "TransportConfig",
    "TransportResult",
    "call_transport",
    "estimate_tokens",
    "dify_business_failed",
    "_iter_sse_data",
]

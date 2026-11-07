"use client";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { evaluationApi } from "@/core/evaluation/api";
import { useI18n } from "@/core/i18n/hooks";

interface RequestSpec {
  version: "request.v1";
  method: string;
  url: string;
  headers: string[][];
  body: string;
}
interface ResponseView {
  status: number;
  elapsed_ms: number;
  size_bytes: number;
  truncated: boolean;
  headers: string[][];
  body: string;
}

export function RequestDebugger() {
  const { locale } = useI18n();
  const zh = locale === "zh-CN";
  const [curl, setCurl] = useState("");
  const [spec, setSpec] = useState<RequestSpec | null>(null);
  const [headers, setHeaders] = useState("[]");
  const [result, setResult] = useState<ResponseView | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [consent, setConsent] = useState(false);
  const [copied, setCopied] = useState(false);
  const change = (patch: Partial<RequestSpec>) => {
    if (spec) setSpec({ ...spec, ...patch });
    setResult(null);
    setConsent(false);
    setCopied(false);
  };
  async function parse() {
    setBusy(true);
    setError("");
    setResult(null);
    setSpec(null);
    setConsent(false);
    try {
      const data = await evaluationApi<{ spec: RequestSpec }>(
        "component-tests/debug/parse",
        { command: curl },
      );
      setSpec(data.spec);
      setHeaders(JSON.stringify(data.spec.headers, null, 2));
      setCurl("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Import failed");
    } finally {
      setBusy(false);
    }
  }
  async function send() {
    if (!spec || !consent) return;
    setBusy(true);
    setError("");
    setResult(null);
    setConsent(false);
    setCopied(false);
    try {
      setResult(
        await evaluationApi<ResponseView>("component-tests/debug/send", {
          spec: { ...spec, headers: JSON.parse(headers) as string[][] },
          consent: true,
        }),
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section
      className="mb-6 space-y-3 rounded-xl border p-4"
      aria-label={zh ? "接口调试" : "Request debugger"}
    >
      <h2 className="text-lg font-semibold">
        {zh ? "接口调试 · 导入完整 cURL" : "Request debugger · Import cURL"}
      </h2>
      <p className="text-muted-foreground text-sm">
        {zh
          ? "粘贴命令后解析，不执行 Shell。凭据仅在当前页面内存中使用，不保存调试历史。暂不支持文件上传、代理、脚本和重定向。"
          : "Parse without a shell. Credentials stay in page memory; no debug history. File upload, proxies, scripts and redirects are not supported yet."}
      </p>
      <label className="block text-sm">
        cURL
        <Textarea
          aria-label="cURL"
          autoComplete="off"
          spellCheck={false}
          value={curl}
          onChange={(e) => setCurl(e.target.value)}
          disabled={busy}
          placeholder={"curl https://example.test/api --json '{}'"}
        />
      </label>
      <Button disabled={busy || !curl.trim()} onClick={() => void parse()}>
        {zh ? "解析 cURL" : "Import cURL"}
      </Button>
      {spec && (
        <fieldset disabled={busy} className="space-y-3">
          <div className="flex gap-2">
            <label className="text-sm">
              {zh ? "方法" : "Method"}
              <select
                className="block rounded border p-2"
                value={spec.method}
                onChange={(e) => change({ method: e.target.value })}
              >
                {[
                  "GET",
                  "POST",
                  "PUT",
                  "PATCH",
                  "DELETE",
                  "HEAD",
                  "OPTIONS",
                ].map((v) => (
                  <option key={v}>{v}</option>
                ))}
              </select>
            </label>
            <label className="flex-1 text-sm">
              URL
              <Input
                aria-label="Request URL"
                value={spec.url}
                onChange={(e) => change({ url: e.target.value })}
              />
            </label>
          </div>
          <label className="block text-sm">
            {zh
              ? "请求头（JSON 键值对，可能包含敏感凭据）"
              : "Headers (JSON pairs; may contain credentials)"}
            <details>
              <summary>
                {zh ? "展开编辑请求头" : "Reveal / edit headers"}
              </summary>
              <Textarea
                aria-label="Request headers"
                autoComplete="off"
                value={headers}
                onChange={(e) => {
                  setHeaders(e.target.value);
                  change({});
                }}
              />
            </details>
          </label>
          <label className="block text-sm">
            {zh ? "请求体" : "Body"}
            <Textarea
              aria-label="Request body"
              value={spec.body}
              onChange={(e) => change({ body: e.target.value })}
            />
          </label>
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
            />
            {zh
              ? "我确认已获授权向此目标发送一次请求（可能产生费用或业务副作用）。目标域名须由管理员加入出站白名单。"
              : "I authorize one request to this operator-approved host, including possible cost or side effects."}
          </label>
          <Button disabled={busy || !consent} onClick={() => void send()}>
            {busy
              ? zh
                ? "请求中…"
                : "Sending…"
              : zh
                ? "发送请求"
                : "Send request"}
          </Button>
          <Button
            className="ml-2"
            variant="outline"
            onClick={() => {
              setSpec(null);
              setHeaders("[]");
              setResult(null);
              setConsent(false);
            }}
          >
            {zh ? "清除凭据与内容" : "Clear request and credentials"}
          </Button>
        </fieldset>
      )}
      {error && (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      )}
      {result && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <strong>HTTP {result.status}</strong>
            <span>{result.elapsed_ms} ms</span>
            <span>{result.size_bytes} B</span>
            {result.truncated && (
              <span>{zh ? "响应已截断（1 MiB）" : "Truncated at 1 MiB"}</span>
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                void navigator.clipboard
                  .writeText(result.body)
                  .then(() => setCopied(true))
                  .catch(() =>
                    setError(
                      zh
                        ? "复制失败，请手动选择文本"
                        : "Copy failed; select text manually",
                    ),
                  );
              }}
            >
              {copied
                ? zh
                  ? "已复制"
                  : "Copied"
                : zh
                  ? "复制响应"
                  : "Copy response"}
            </Button>
          </div>
          <details>
            <summary>{zh ? "响应头" : "Response headers"}</summary>
            <pre className="overflow-auto text-xs">
              {JSON.stringify(result.headers, null, 2)}
            </pre>
          </details>
          <pre
            aria-label="Response body"
            className="bg-muted max-h-96 overflow-auto rounded p-3 text-xs whitespace-pre-wrap"
          >
            {result.body}
          </pre>
        </div>
      )}
    </section>
  );
}

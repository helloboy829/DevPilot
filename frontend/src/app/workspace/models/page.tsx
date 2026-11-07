"use client";

import { Copy, Plus, Search, Settings2, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { evaluationApi } from "@/core/evaluation/api";
import { useI18n } from "@/core/i18n/hooks";

interface Parameters {
  temperature: number | null;
  top_p: number | null;
  max_tokens: number | null;
  timeout_seconds: number;
  max_retries: number;
}
interface Profile {
  name: string;
  display_name: string;
  provider: string;
  provider_name: string;
  model: string;
  base_url: string;
  enabled: boolean;
  parameters: Parameters;
}
interface PublicModel extends Profile {
  has_credential: boolean;
}
interface Catalog {
  revision: number;
  models: PublicModel[];
  roles: Record<string, string | null>;
}
const defaults: Parameters = {
  temperature: null,
  top_p: null,
  max_tokens: null,
  timeout_seconds: 60,
  max_retries: 0,
};
const blank: Profile = {
  name: "",
  display_name: "",
  provider: "openai_compatible",
  provider_name: "",
  model: "",
  base_url: "",
  enabled: true,
  parameters: defaults,
};
const protocols = [
  {
    id: "openai_compatible",
    name: "OpenAI Chat Completions",
    endpoint: "https://api.openai.com/v1",
    path: "/chat/completions",
  },
  {
    id: "openai_responses",
    name: "OpenAI Responses",
    endpoint: "https://api.openai.com/v1",
    path: "/responses",
  },
  {
    id: "anthropic",
    name: "Anthropic Messages",
    endpoint: "https://api.anthropic.com",
    path: "/v1/messages",
  },
  {
    id: "gemini",
    name: "Gemini Developer API",
    endpoint: "https://generativelanguage.googleapis.com",
    path: "generateContent",
  },
];
const roleNames = {
  general_agent: ["通用 Agent（默认模型）", "General agent (default)"],
  report_advisor: ["报告助手", "Report advisor"],
  dataset_generator: ["数据构建（预留绑定）", "Dataset generation (reserved)"],
  evaluator_judge: ["效果裁判（预留绑定）", "Evaluation judge (reserved)"],
  review_assistant: ["复核助手（预留绑定）", "Review assistant (reserved)"],
};
function editable(m: PublicModel): Profile {
  return {
    name: m.name,
    display_name: m.display_name,
    provider: m.provider,
    provider_name: m.provider_name ?? "",
    model: m.model,
    base_url: m.base_url,
    enabled: m.enabled,
    parameters: { ...defaults, ...m.parameters },
  };
}
export default function ModelsPage() {
  const { locale } = useI18n();
  const zh = locale === "zh-CN";
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [form, setForm] = useState<Profile>(blank);
  const [key, setKey] = useState("");
  const [clearKey, setClearKey] = useState(false);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [probeConsent, setProbeConsent] = useState(false);
  const [search, setSearch] = useState("");
  useEffect(() => {
    let active = true;
    void evaluationApi<Catalog>("model-management")
      .then((data) => {
        if (active) setCatalog(data);
      })
      .catch((e: unknown) => {
        if (active) setError(e instanceof Error ? e.message : "Unavailable");
      });
    return () => {
      active = false;
    };
  }, []);
  function reset() {
    setEditing(false);
    setForm({ ...blank, parameters: { ...defaults } });
    setKey("");
    setClearKey(false);
  }
  async function mutate(route: string, body?: unknown, method = "POST") {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      setCatalog(await evaluationApi<Catalog>(route, body, method));
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
      return false;
    } finally {
      setBusy(false);
    }
  }
  const filtered =
    catalog?.models.filter((m) =>
      [m.name, m.display_name, m.provider_name, m.model, m.provider]
        .join(" ")
        .toLowerCase()
        .includes(search.toLowerCase()),
    ) ?? [];
  const selectedProtocol = protocols.find((p) => p.id === form.provider);
  return (
    <WorkspaceContainer>
      <WorkspaceHeader>
        <h1 className="text-lg font-semibold">
          {zh ? "模型连接与角色路由" : "Model connections & role routing"}
        </h1>
      </WorkspaceHeader>
      <WorkspaceBody className="overflow-y-auto">
        <div className="mx-auto w-full max-w-7xl space-y-6 p-4 md:p-8">
          <section className="to-background flex flex-wrap items-start justify-between gap-5 rounded-2xl border bg-gradient-to-r from-indigo-500/10 p-6">
            <div className="max-w-3xl">
              <p className="text-muted-foreground mb-2 text-xs font-semibold tracking-widest">
                MODEL CONTROL CENTER
              </p>
              <h2 className="text-2xl font-semibold">
                {zh
                  ? "连接可切换，模型各司其职。"
                  : "Switch connections. Give each model a role."}
              </h2>
              <p className="text-muted-foreground mt-3 text-sm leading-6">
                {zh
                  ? "服务商可以自定义；协议决定请求格式，模型 ID 决定实际调用对象，角色决定平台把任务交给谁。这是平台工作模型配置，不是被测组件配置。"
                  : "Providers are customizable. Protocol chooses the wire format, model ID selects the model, and roles route platform work. These are working models, not evaluation targets."}
              </p>
            </div>
            <ShieldCheck className="text-primary size-8" />
          </section>
          <div aria-live="polite">
            {error && (
              <p
                role="alert"
                className="text-destructive rounded-lg border p-3 text-sm"
              >
                {error}
              </p>
            )}
            {message && (
              <p role="status" className="rounded-lg border p-3 text-sm">
                {message}
              </p>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => {
                setBusy(true);
                void evaluationApi<Catalog>("model-management")
                  .then(setCatalog)
                  .catch((e: unknown) =>
                    setError(e instanceof Error ? e.message : "Reload failed"),
                  )
                  .finally(() => setBusy(false));
              }}
            >
              {zh ? "重新加载目录" : "Reload catalog"}
            </Button>
            <p className="text-muted-foreground text-xs">
              {zh
                ? "仅管理员可管理；密钥加密存储且不回显。修改冲突时请重新加载。"
                : "Administrators only. Credentials are encrypted and write-only. Reload on revision conflicts."}
            </p>
          </div>
          {catalog && (
            <>
              <div className="grid items-start gap-6 xl:grid-cols-[1fr_1.1fr]">
                <section className="bg-card space-y-4 rounded-xl border p-5">
                  <div className="flex items-center justify-between gap-3">
                    <h2 className="font-semibold">
                      {zh ? "连接配置" : "Connection profiles"} ·{" "}
                      {catalog.models.length}
                    </h2>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={busy}
                      onClick={reset}
                    >
                      <Plus className="size-4" />
                      {zh ? "新建配置" : "New profile"}
                    </Button>
                  </div>
                  <label className="flex items-center gap-2">
                    <Search className="text-muted-foreground size-4" />
                    <Input
                      aria-label={zh ? "搜索连接配置" : "Search profiles"}
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                      placeholder={
                        zh
                          ? "服务商、模型或协议"
                          : "Provider, model or protocol"
                      }
                    />
                  </label>
                  {filtered.length === 0 && (
                    <p className="text-muted-foreground rounded-lg border border-dashed p-5 text-sm">
                      {zh
                        ? "没有匹配的连接配置。新建一个，或调整搜索条件。"
                        : "No matching profiles. Create one or change the search."}
                    </p>
                  )}
                  <div className="space-y-3">
                    {filtered.map((m) => (
                      <article
                        key={m.name}
                        className="space-y-3 rounded-xl border p-4"
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <h3 className="font-semibold">
                              {m.display_name || m.name}
                            </h3>
                            <p className="text-muted-foreground mt-1 text-xs break-all">
                              {m.provider_name ||
                                (zh ? "自定义服务商" : "Custom provider")}{" "}
                              · {m.model}
                            </p>
                          </div>
                          <span className="rounded border px-2 py-1 text-xs">
                            {m.enabled
                              ? zh
                                ? "启用"
                                : "Enabled"
                              : zh
                                ? "停用"
                                : "Disabled"}
                          </span>
                        </div>
                        <p className="text-muted-foreground text-xs">
                          {protocols.find((p) => p.id === m.provider)?.name ??
                            m.provider}{" "}
                          ·{" "}
                          {m.has_credential
                            ? zh
                              ? "凭据已设置"
                              : "Credential set"
                            : zh
                              ? "无凭据"
                              : "No credential"}
                        </p>
                        <div className="flex flex-wrap gap-1">
                          {Object.entries(catalog.roles)
                            .filter(([, id]) => id === m.name)
                            .map(([role]) => (
                              <span
                                key={role}
                                className="bg-primary/10 rounded px-2 py-1 text-xs"
                              >
                                {role}
                              </span>
                            ))}
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={busy}
                            onClick={() => {
                              setEditing(true);
                              setForm(editable(m));
                              setKey("");
                              setClearKey(false);
                            }}
                          >
                            {zh ? "编辑" : "Edit"}
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            disabled={busy}
                            onClick={() => {
                              setEditing(false);
                              setForm({
                                ...editable(m),
                                name: "",
                                display_name: "",
                              });
                              setKey("");
                              setClearKey(false);
                              setMessage(
                                zh
                                  ? "已复制非凭据配置，请填写新 ID 和凭据。"
                                  : "Non-secret settings copied. Enter a new ID and credential.",
                              );
                            }}
                          >
                            <Copy className="size-3" />
                            {zh ? "复制为新配置" : "Duplicate profile"}
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={
                              busy ||
                              !m.enabled ||
                              catalog.roles.general_agent === m.name
                            }
                            onClick={() =>
                              void mutate(
                                "model-management/roles",
                                {
                                  roles: { general_agent: m.name },
                                  revision: catalog.revision,
                                },
                                "PUT",
                              )
                            }
                          >
                            {zh ? "设为默认" : "Use as default"}
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            disabled={busy || !probeConsent || !m.enabled}
                            onClick={() => {
                              setBusy(true);
                              setError("");
                              setProbeConsent(false);
                              void evaluationApi(
                                "model-management/models/" +
                                  encodeURIComponent(m.name) +
                                  "/probe",
                                { consent: true },
                              )
                                .then(() =>
                                  setMessage(
                                    zh
                                      ? "连通性测试成功"
                                      : "Connectivity check succeeded",
                                  ),
                                )
                                .catch((e: unknown) =>
                                  setError(
                                    e instanceof Error
                                      ? e.message
                                      : "Probe failed",
                                  ),
                                )
                                .finally(() => setBusy(false));
                            }}
                          >
                            {zh ? "测试连接" : "Test connection"}
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            disabled={
                              busy ||
                              Object.values(catalog.roles).includes(m.name)
                            }
                            onClick={() => {
                              if (
                                window.confirm(
                                  zh
                                    ? "删除此模型配置？"
                                    : "Delete this model configuration?",
                                )
                              )
                                void mutate(
                                  "model-management/models/" +
                                    encodeURIComponent(m.name) +
                                    "?revision=" +
                                    catalog.revision,
                                  undefined,
                                  "DELETE",
                                );
                            }}
                          >
                            {zh ? "删除" : "Delete"}
                          </Button>
                        </div>
                      </article>
                    ))}
                  </div>
                  <label className="flex items-start gap-2 text-xs leading-5">
                    <input
                      type="checkbox"
                      checked={probeConsent}
                      disabled={busy}
                      onChange={(e) => setProbeConsent(e.target.checked)}
                    />
                    {zh
                      ? "同意发送一次固定非业务提示进行连接测试，可能产生费用。"
                      : "Authorize one fixed, non-business connectivity prompt; charges may apply."}
                  </label>
                </section>
                <form
                  className="bg-card space-y-4 rounded-xl border p-5"
                  onSubmit={(e) => {
                    e.preventDefault();
                    void mutate(
                      "model-management/models",
                      {
                        revision: catalog.revision,
                        model: {
                          ...form,
                          ...(key ? { api_key: key } : {}),
                          ...(clearKey ? { clear_credential: true } : {}),
                        },
                      },
                      "PUT",
                    ).then((ok) => {
                      if (ok) {
                        reset();
                        setMessage(
                          zh ? "模型配置已保存" : "Model profile saved",
                        );
                      }
                    });
                  }}
                >
                  <h2 className="flex items-center gap-2 font-semibold">
                    <Settings2 className="size-5" />
                    {editing
                      ? zh
                        ? "编辑连接配置"
                        : "Edit connection profile"
                      : zh
                        ? "新建连接配置"
                        : "New connection profile"}
                  </h2>
                  <fieldset disabled={busy} className="space-y-4">
                    {!editing && (
                      <div>
                        <p className="text-muted-foreground mb-2 text-xs">
                          {zh
                            ? "从协议预设开始（只填地址和格式，不绑定商业服务商）"
                            : "Start from a protocol preset (endpoint and format only)"}
                        </p>
                        <div className="flex flex-wrap gap-2">
                          {protocols.map((protocol) => (
                            <Button
                              key={protocol.id}
                              type="button"
                              size="sm"
                              variant="outline"
                              onClick={() => {
                                setForm({
                                  ...form,
                                  provider: protocol.id,
                                  base_url: protocol.endpoint,
                                });
                                setKey("");
                                setClearKey(false);
                              }}
                            >
                              {protocol.name}
                            </Button>
                          ))}
                        </div>
                      </div>
                    )}
                    <div className="grid gap-3 sm:grid-cols-2">
                      {(
                        [
                          ["name", zh ? "配置 ID" : "Configuration ID"],
                          ["display_name", zh ? "显示名称" : "Display name"],
                          [
                            "provider_name",
                            zh
                              ? "服务商名称（可自定义）"
                              : "Provider name (customizable)",
                          ],
                          ["model", zh ? "服务商模型 ID" : "Provider model ID"],
                          ["base_url", zh ? "API 基础地址" : "API Base URL"],
                        ] as const
                      ).map(([field, label]) => (
                        <label
                          key={field}
                          className={
                            field === "base_url"
                              ? "text-sm sm:col-span-2"
                              : "text-sm"
                          }
                        >
                          {label}
                          <Input
                            className="mt-1"
                            required={
                              field === "name" ||
                              field === "model" ||
                              field === "base_url"
                            }
                            disabled={field === "name" && editing}
                            type={field === "base_url" ? "url" : "text"}
                            maxLength={
                              field === "base_url"
                                ? 2048
                                : field === "name"
                                  ? 64
                                  : field === "model"
                                    ? 200
                                    : 100
                            }
                            value={form[field]}
                            onChange={(e) =>
                              setForm({ ...form, [field]: e.target.value })
                            }
                          />
                        </label>
                      ))}
                    </div>
                    <label className="block text-sm">
                      {zh ? "协议适配器" : "Provider adapter"}
                      <select
                        className="bg-background mt-1 block w-full rounded border p-2"
                        value={form.provider}
                        onChange={(e) =>
                          setForm({ ...form, provider: e.target.value })
                        }
                      >
                        {protocols.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.name}
                          </option>
                        ))}
                      </select>
                    </label>
                    <p className="text-muted-foreground text-xs">
                      {zh ? "SDK 使用上方基础地址构建" : "SDK builds"}{" "}
                      {selectedProtocol?.path}{" "}
                      {zh
                        ? "请求，请勿填写完整推理接口路径。兼容服务需支持所选协议。"
                        : "requests from the base URL above. Do not paste the full inference path. Gateways must support the selected protocol."}
                    </p>
                    <label className="block text-sm">
                      API Key
                      <Input
                        className="mt-1"
                        type="password"
                        autoComplete="new-password"
                        value={key}
                        disabled={clearKey}
                        onChange={(e) => setKey(e.target.value)}
                      />
                    </label>
                    <p className="text-muted-foreground text-xs leading-5">
                      {zh
                        ? "留空保留原密钥；更换地址或协议时必须重新填写或明确清除，防止向新地址泄露旧密钥。复制配置不会复制密钥。"
                        : "Blank retains the existing key. Changing endpoint or protocol requires a new key or explicit removal. Duplicating a profile never copies its credential."}
                    </p>
                    {editing && (
                      <label className="flex items-center gap-2 text-sm">
                        <input
                          type="checkbox"
                          checked={clearKey}
                          onChange={(e) => {
                            setClearKey(e.target.checked);
                            setKey("");
                          }}
                        />
                        {zh
                          ? "明确清除已保存的凭据"
                          : "Explicitly remove saved credential"}
                      </label>
                    )}
                    <details className="rounded-lg border p-3">
                      <summary className="cursor-pointer text-sm font-medium">
                        {zh
                          ? "高级参数（可选）"
                          : "Advanced parameters (optional)"}
                      </summary>
                      <p className="text-muted-foreground my-3 text-xs">
                        {zh
                          ? "留空采样/输出上限将沿用 SDK 默认值，模型须支持所填参数；报告助手会施加更严格的调用限制。"
                          : "Blank sampling/output limits use SDK defaults; the model must support supplied values. Report calls apply stricter limits."}
                      </p>
                      <div className="grid gap-3 sm:grid-cols-2">
                        {(
                          [
                            ["temperature", "Temperature", 0, 2, 0.1],
                            ["top_p", "Top P", 0.01, 1, 0.01],
                            [
                              "max_tokens",
                              zh ? "最大输出 tokens" : "Max output tokens",
                              1,
                              65536,
                              1,
                            ],
                            [
                              "timeout_seconds",
                              zh ? "超时（秒）" : "Timeout (seconds)",
                              1,
                              300,
                              1,
                            ],
                            [
                              "max_retries",
                              zh ? "重试次数" : "Retries",
                              0,
                              2,
                              1,
                            ],
                          ] as const
                        ).map(([field, label, min, max, step]) => (
                          <label key={field} className="text-sm">
                            {label}
                            <Input
                              type="number"
                              min={min}
                              max={max}
                              step={step}
                              required={
                                field === "timeout_seconds" ||
                                field === "max_retries"
                              }
                              value={form.parameters[field] ?? ""}
                              onChange={(e) => {
                                const value =
                                  e.target.value === ""
                                    ? null
                                    : Number(e.target.value);
                                setForm({
                                  ...form,
                                  parameters: {
                                    ...form.parameters,
                                    [field]: value,
                                  },
                                });
                              }}
                            />
                          </label>
                        ))}
                      </div>
                    </details>
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={form.enabled}
                        onChange={(e) =>
                          setForm({ ...form, enabled: e.target.checked })
                        }
                      />
                      {zh
                        ? "启用（停用前先解除角色绑定）"
                        : "Enabled (unassign roles before disabling)"}
                    </label>
                    <div className="flex gap-3">
                      <Button type="submit">
                        {zh ? "保存配置" : "Save model"}
                      </Button>
                      <Button type="button" variant="ghost" onClick={reset}>
                        {zh ? "清空" : "Clear"}
                      </Button>
                    </div>
                  </fieldset>
                </form>
              </div>
              <section className="bg-card space-y-4 rounded-xl border p-5">
                <h2 className="font-semibold">
                  {zh ? "按工作角色分配模型" : "Assign models by role"}
                </h2>
                <p className="text-muted-foreground text-sm">
                  {zh
                    ? "通用 Agent 与报告助手已接通；其余三项仅预留配置，尚未实现对应流水线。聊天可单次切换模型。角色分工不是自动并行调用，也不会自动故障转移。"
                    : "General agent and report advisor are connected. The other three bindings reserve configuration; their pipelines are not implemented. Chat supports per-conversation selection. Role routing is not automatic parallel execution or failover."}
                </p>
                <div className="grid gap-4 md:grid-cols-2">
                  {Object.entries(roleNames).map(([role, names]) => (
                    <label key={role} className="rounded-lg border p-3 text-sm">
                      <span>{names[zh ? 0 : 1]}</span>
                      <select
                        aria-label={role}
                        disabled={busy}
                        className="bg-background mt-2 block w-full rounded border p-2"
                        value={catalog.roles[role] ?? ""}
                        onChange={(e) =>
                          void mutate(
                            "model-management/roles",
                            {
                              roles: { [role]: e.target.value || null },
                              revision: catalog.revision,
                            },
                            "PUT",
                          )
                        }
                      >
                        <option value="">
                          {zh
                            ? "未绑定 / 使用运营配置"
                            : "Unassigned / operator default"}
                        </option>
                        {catalog.models
                          .filter((m) => m.enabled)
                          .map((m) => (
                            <option key={m.name} value={m.name}>
                              {m.display_name || m.name}
                            </option>
                          ))}
                      </select>
                    </label>
                  ))}
                </div>
              </section>
            </>
          )}
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

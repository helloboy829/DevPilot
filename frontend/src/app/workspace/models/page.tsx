"use client";
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

interface Model {
  name: string;
  display_name: string;
  provider: string;
  model: string;
  base_url: string;
  enabled: boolean;
  has_credential: boolean;
}
interface Catalog {
  revision: number;
  models: Model[];
  roles: Record<string, string | null>;
}
const blank = {
  name: "",
  display_name: "",
  provider: "openai_compatible",
  model: "",
  base_url: "",
  enabled: true,
};
const roleNames = {
  general_agent: ["通用 Agent（默认模型）", "General agent (default)"],
  report_advisor: ["报告助手", "Report advisor"],
  dataset_generator: ["数据构建（预留绑定）", "Dataset generation (reserved)"],
  evaluator_judge: ["效果裁判（预留绑定）", "Evaluation judge (reserved)"],
  review_assistant: ["复核助手（预留绑定）", "Review assistant (reserved)"],
};

export default function ModelsPage() {
  const { locale } = useI18n();
  const zh = locale === "zh-CN";
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [form, setForm] = useState(blank);
  const [key, setKey] = useState("");
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [probeConsent, setProbeConsent] = useState(false);
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
  async function mutate(route: string, body?: unknown, method = "POST") {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const next = await evaluationApi<Catalog>(route, body, method);
      setCatalog(next);
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
      return false;
    } finally {
      setBusy(false);
    }
  }
  return (
    <WorkspaceContainer>
      <WorkspaceHeader>
        <h1 className="text-lg font-semibold">
          {zh ? "模型与分工" : "Models & roles"}
        </h1>
      </WorkspaceHeader>
      <WorkspaceBody>
        <div className="mx-auto w-full max-w-5xl space-y-6 p-6">
          <p className="text-muted-foreground text-sm">
            {zh
              ? "管理员维护平台工作模型，与被测组件分开。凭据加密存储且不会回显；留空则保留原凭据。绑定报告助手即启用该功能，每次调用仍需评测者同意。"
              : "Administrator-managed platform models are separate from targets. Credentials are encrypted and write-only; leave blank to retain. Assigning the report role enables its opt-in advisor."}
          </p>
          {error && (
            <p role="alert" className="text-destructive">
              {error}
            </p>
          )}
          {message && <p role="status">{message}</p>}
          {catalog && (
            <>
              <section className="space-y-3 rounded-xl border p-4">
                <h2 className="font-semibold">
                  {zh ? "工作模型列表" : "Model catalog"}
                </h2>
                {catalog.models.length === 0 && (
                  <p>
                    {zh
                      ? "尚未配置模型，请在下方添加。"
                      : "No models configured. Add one below."}
                  </p>
                )}
                {catalog.models.map((m) => (
                  <div
                    key={m.name}
                    className="flex flex-wrap items-center gap-3 rounded border p-3"
                  >
                    <div className="flex-1">
                      <strong>{m.display_name || m.name}</strong>
                      <p className="text-muted-foreground text-sm">
                        {m.name} · {m.model} ·{" "}
                        {m.enabled
                          ? zh
                            ? "启用"
                            : "Enabled"
                          : zh
                            ? "停用"
                            : "Disabled"}{" "}
                        ·{" "}
                        {m.has_credential
                          ? zh
                            ? "凭据已设置"
                            : "Credential set"
                          : zh
                            ? "无凭据"
                            : "No credential"}
                      </p>
                    </div>
                    <Button
                      disabled={busy}
                      variant="outline"
                      onClick={() => {
                        setEditing(true);
                        setForm({
                          name: m.name,
                          display_name: m.display_name,
                          provider: m.provider,
                          model: m.model,
                          base_url: m.base_url,
                          enabled: m.enabled,
                        });
                        setKey("");
                      }}
                    >
                      {zh ? "编辑" : "Edit"}
                    </Button>
                    <Button
                      disabled={busy || !probeConsent || !m.enabled}
                      variant="outline"
                      onClick={() => {
                        setBusy(true);
                        setError("");
                        setProbeConsent(false);
                        void evaluationApi<{ ok: boolean }>(
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
                              e instanceof Error ? e.message : "Probe failed",
                            ),
                          )
                          .finally(() => setBusy(false));
                      }}
                    >
                      {zh ? "测试连接" : "Test connection"}
                    </Button>
                    <Button
                      disabled={
                        busy || Object.values(catalog.roles).includes(m.name)
                      }
                      variant="outline"
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
                ))}
                <label className="flex gap-2 text-sm">
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
                className="grid gap-3 rounded-xl border p-4 sm:grid-cols-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (busy) return;
                  void mutate(
                    "model-management/models",
                    {
                      model: { ...form, ...(key ? { api_key: key } : {}) },
                      revision: catalog.revision,
                    },
                    "PUT",
                  ).then((ok) => {
                    setKey("");
                    if (ok) {
                      setForm(blank);
                      setEditing(false);
                    }
                  });
                }}
              >
                <h2 className="font-semibold sm:col-span-2">
                  {editing
                    ? zh
                      ? "编辑模型"
                      : "Edit model"
                    : zh
                      ? "添加模型"
                      : "Add model"}
                </h2>
                <fieldset disabled={busy} className="contents">
                  {(["name", "display_name", "model", "base_url"] as const).map(
                    (field) => (
                      <label key={field} className="text-sm">
                        {
                          {
                            name: zh
                              ? "配置标识（英文、数字、下划线）"
                              : "Configuration ID",
                            display_name: zh ? "显示名称" : "Display name",
                            model: zh ? "服务商模型 ID" : "Provider model ID",
                            base_url: zh ? "API Base URL" : "API Base URL",
                          }[field]
                        }
                        <Input
                          required={field !== "display_name"}
                          disabled={field === "name" && editing}
                          value={form[field]}
                          onChange={(e) =>
                            setForm({ ...form, [field]: e.target.value })
                          }
                        />
                      </label>
                    ),
                  )}
                  <label className="text-sm">
                    {zh ? "协议适配器" : "Provider adapter"}
                    <select
                      className="block w-full rounded border p-2"
                      value={form.provider}
                      onChange={(e) =>
                        setForm({ ...form, provider: e.target.value })
                      }
                    >
                      <option value="openai_compatible">
                        OpenAI-compatible
                      </option>
                      <option value="anthropic">Anthropic</option>
                    </select>
                  </label>
                  <label className="text-sm">
                    API Key
                    <Input
                      type="password"
                      autoComplete="new-password"
                      value={key}
                      onChange={(e) => setKey(e.target.value)}
                    />
                  </label>
                  <label className="flex gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={form.enabled}
                      onChange={(e) =>
                        setForm({ ...form, enabled: e.target.checked })
                      }
                    />
                    {zh
                      ? "启用（停用前需解除角色绑定）"
                      : "Enabled (unassign roles before disabling)"}
                  </label>
                  <div>
                    <Button type="submit" disabled={busy}>
                      {zh ? "保存配置" : "Save model"}
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      onClick={() => {
                        setEditing(false);
                        setForm(blank);
                        setKey("");
                      }}
                    >
                      {zh ? "清空" : "Clear"}
                    </Button>
                  </div>
                </fieldset>
              </form>
              <section className="space-y-3 rounded-xl border p-4">
                <h2 className="font-semibold">
                  {zh ? "按工作角色分配模型" : "Assign models by role"}
                </h2>
                <p className="text-muted-foreground text-sm">
                  {zh
                    ? "通用 Agent 与报告助手已接通；其余角色仅保存分工配置，不表示评测流水线已实现。聊天输入框仍可为单次会话选择模型。"
                    : "General agent and report advisor are connected. Other roles reserve configuration only; their pipelines are not implemented. Chat can override the default per conversation."}
                </p>
                {Object.entries(roleNames).map(([role, names]) => (
                  <label
                    key={role}
                    className="flex flex-wrap items-center justify-between gap-3 text-sm"
                  >
                    {names[zh ? 0 : 1]}
                    <select
                      aria-label={role}
                      disabled={busy}
                      className="min-w-48 rounded border p-2"
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
              </section>
            </>
          )}
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

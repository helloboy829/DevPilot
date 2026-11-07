"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { ProjectComponent } from "@/core/datasets/registry-types";
import type { DatasetVersion } from "@/core/datasets/types";
import { evaluationApi } from "@/core/evaluation/api";
import {
  buildPlanPayload,
  initialPlanForm,
  type PlanForm,
} from "@/core/evaluation/plan-form";
import type { FrozenPlan, PlanCreate } from "@/core/evaluation/plan-types";
import type { RequestVersionMetadata } from "@/core/evaluation/request-version-types";

const selectStyle =
  "bg-background w-full min-w-0 rounded-md border px-3 py-2 text-sm";

/** Mounted with key=projectId. No gold, complete request, execution, or browser cache. */
export function EvaluationPlanPanel({
  projectId,
  zh,
}: {
  projectId: string;
  zh: boolean;
}) {
  const [components, setComponents] = useState<ProjectComponent[]>([]);
  const [datasets, setDatasets] = useState<DatasetVersion[]>([]);
  const [versions, setVersions] = useState<RequestVersionMetadata[]>([]);
  const [plans, setPlans] = useState<FrozenPlan[]>([]);
  const [componentId, setComponentId] = useState("");
  const [requestId, setRequestId] = useState("");
  const [datasetId, setDatasetId] = useState("");
  const [form, setForm] = useState(initialPlanForm);
  const [loaded, setLoaded] = useState(false);
  const [versionsLoaded, setVersionsLoaded] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [writeBlocked, setWriteBlocked] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const epoch = useRef(0);
  const lock = useRef(false);
  const base = `evaluation/projects/${encodeURIComponent(projectId)}`;
  const request = versions.find((row) => row.id === requestId);
  const dataset = datasets.find(
    (row) => row.id === datasetId && row.status === "frozen",
  );
  let preview: PlanCreate | undefined;
  try {
    preview = buildPlanPayload(
      form,
      projectId,
      componentId,
      request,
      dataset,
      true,
    );
  } catch {
    /* Incomplete form: never submit. */
  }

  useEffect(() => {
    const lifecycle = epoch;
    return () => {
      lifecycle.current++;
    };
  }, []);

  function revoke() {
    setConfirmed(false);
    setNotice("");
  }
  function edit(patch: Partial<PlanForm>) {
    setForm((current) => ({ ...current, ...patch }));
    revoke();
  }
  async function operate(
    action: (token: number) => Promise<void>,
    writing = false,
  ) {
    if (lock.current) return;
    lock.current = true;
    const token = epoch.current;
    setBusy(true);
    setError("");
    revoke();
    try {
      await action(token);
    } catch {
      if (token === epoch.current) {
        if (writing) setWriteBlocked(true);
        setError(
          zh
            ? "操作未确认成功，可能涉及权限、密钥、版本冲突、映射或预算。请刷新并核对已有版本后重新确认；不会自动重试写入。"
            : "Operation not confirmed: permissions, encryption key, version conflict, mapping or budget. Refresh and inspect existing versions before confirming again; writes are never retried automatically.",
        );
      }
    } finally {
      lock.current = false;
      if (token === epoch.current) setBusy(false);
    }
  }
  function resetSelection() {
    setRequestId("");
    setDatasetId("");
    setVersions([]);
    setPlans([]);
    setVersionsLoaded(false);
    revoke();
  }
  async function loadSources(token: number) {
    setLoaded(false);
    setComponentId("");
    setComponents([]);
    setDatasets([]);
    resetSelection();
    setForm(initialPlanForm());
    const [links, data] = await Promise.all([
      evaluationApi<{ components: ProjectComponent[] }>(base + "/components"),
      evaluationApi<{ datasets: DatasetVersion[] }>(base + "/datasets"),
    ]);
    if (token !== epoch.current) return;
    setComponents(links.components);
    setDatasets(data.datasets);
    setLoaded(true);
    setWriteBlocked(false);
  }
  async function loadVersions(id: string, token: number) {
    resetSelection();
    setDatasets([]);
    if (!id) return;
    const path = base + "/components/" + encodeURIComponent(id);
    const [requests, frozen, data] = await Promise.all([
      evaluationApi<{ request_versions: RequestVersionMetadata[] }>(
        path + "/request-versions",
      ),
      evaluationApi<{ plans: FrozenPlan[] }>(path + "/plans"),
      evaluationApi<{ datasets: DatasetVersion[] }>(base + "/datasets"),
    ]);
    if (token !== epoch.current) return;
    setVersions(requests.request_versions);
    setPlans(frozen.plans);
    setDatasets(data.datasets);
    setVersionsLoaded(true);
    setWriteBlocked(false);
  }
  const t = (en: string, cn: string) => (zh ? cn : en);
  return (
    <section
      aria-label={t("Frozen QA plans", "冻结 QA 评测计划")}
      className="min-w-0 space-y-4 rounded-xl border p-5"
    >
      <div className="space-y-2">
        <h2 className="font-semibold">
          {t("Frozen QA plans", "冻结 QA 评测计划")}
        </h2>
        <p className="text-muted-foreground text-sm leading-6">
          {t(
            "Pin a request version, frozen QA version, JSON mappings and limits. This does not start testing or approve execution. No model is needed; encrypted request storage and preflight require the operator's separate key.",
            "固定请求版本、已冻结 QA 版本、JSON 字段映射与参数。这里只冻结定义，不启动测试、不批准执行。无需工作模型；加密请求保存和预检需要运维配置独立密钥。",
          )}
        </p>
        <p className="text-muted-foreground text-xs">
          {t(
            "JSON text only. No TTFT, SSE, CV or token-rate measurement. Body budget excludes responses, headers and provider billing.",
            "仅支持 JSON 文本。不生成 TTFT、不处理 SSE、CV 或 token 速率。正文预算不包含响应、请求头和服务商账单。",
          )}
        </p>
      </div>
      <Button
        variant="outline"
        disabled={busy}
        onClick={() => void operate(loadSources)}
      >
        {t("Load / refresh plan sources", "加载 / 刷新计划来源")}
      </Button>
      {error && (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="rounded-md border p-3 text-sm">
          {notice}
        </p>
      )}
      {!loaded && (
        <p className="text-muted-foreground text-sm">
          {t(
            "Load project sources to begin. Saved definitions remain on the server; this form is page-memory only.",
            "请加载项目来源。已冻结定义保存在服务端，当前表单仅保留在本页内存中。",
          )}
        </p>
      )}
      <fieldset disabled={busy || !loaded} className="min-w-0 space-y-4">
        <legend className="mb-2 text-sm font-medium">
          {t("1. Select a project component", "1. 选择项目组件")}
        </legend>
        <label className="block space-y-1 text-sm">
          <span>{t("Plan component", "计划组件")}</span>
          <select
            className={selectStyle}
            value={componentId}
            onChange={(event) => {
              const id = event.target.value;
              setComponentId(id);
              setForm(initialPlanForm());
              void operate((token) => loadVersions(id, token));
            }}
          >
            <option value="">
              {t("Select a linked component", "选择已加入项目的组件")}
            </option>
            {components.map((row) => (
              <option key={row.id} value={row.id}>
                {row.name_at_link} · {row.kind}
              </option>
            ))}
          </select>
        </label>
        {loaded && components.length === 0 && (
          <p className="text-muted-foreground text-sm">
            {t(
              "Link a registered component using the project registry above, then refresh.",
              "请在上方项目清单中关联已登记组件，然后刷新。",
            )}
          </p>
        )}
        <Button
          variant="outline"
          disabled={!componentId}
          onClick={() =>
            void operate((token) => loadVersions(componentId, token))
          }
        >
          {t("Refresh versions and plans", "刷新版本与计划")}
        </Button>
      </fieldset>
      <fieldset
        disabled={busy || !versionsLoaded}
        className="min-w-0 space-y-4"
      >
        <legend className="mb-2 text-sm font-medium">
          {t("2. Pin sources and field mappings", "2. 固定来源与字段映射")}
        </legend>
        <div className="grid min-w-0 gap-4 md:grid-cols-2">
          <label className="block min-w-0 space-y-1 text-sm">
            <span>{t("Request version", "请求版本")}</span>
            <select
              className={selectStyle}
              value={requestId}
              onChange={(e) => {
                setRequestId(e.target.value);
                revoke();
              }}
            >
              <option value="">
                {t(
                  "Select encrypted request metadata",
                  "选择加密请求版本元数据",
                )}
              </option>
              {versions.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.version_label}
                </option>
              ))}
            </select>
          </label>
          <label className="block min-w-0 space-y-1 text-sm">
            <span>{t("QA dataset version", "QA 数据版本")}</span>
            <select
              className={selectStyle}
              value={datasetId}
              onChange={(e) => {
                setDatasetId(e.target.value);
                revoke();
              }}
            >
              <option value="">
                {t("Select a frozen dataset", "选择已冻结数据集")}
              </option>
              {datasets
                .filter((row) => row.status === "frozen")
                .map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.name} · r{row.revision} · {row.purpose} ·{" "}
                    {row.sample_count}
                  </option>
                ))}
            </select>
          </label>
          <label className="block space-y-1 text-sm">
            <span>{t("Plan version label", "计划版本名称")}</span>
            <Input
              maxLength={80}
              value={form.versionLabel}
              onChange={(e) => edit({ versionLabel: e.target.value })}
            />
          </label>
          <label className="block space-y-1 text-sm">
            <span>{t("Input JSON pointer", "输入 JSON 指针")}</span>
            <Input
              value={form.inputPointer}
              placeholder="/messages/0/content"
              onChange={(e) => edit({ inputPointer: e.target.value })}
            />
          </label>
          <label className="block space-y-1 text-sm">
            <span>{t("Output JSON pointer", "输出 JSON 指针")}</span>
            <Input
              disabled={form.rootOutput}
              value={form.outputPointer}
              placeholder="/choices/0/message/content"
              onChange={(e) => edit({ outputPointer: e.target.value })}
            />
          </label>
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-1"
              checked={form.rootOutput}
              onChange={(e) => edit({ rootOutput: e.target.checked })}
            />
            <span>
              {t(
                "Response root is a JSON string",
                "响应根节点本身是 JSON 字符串",
              )}
            </span>
          </label>
        </div>
        <p className="text-muted-foreground text-xs leading-5">
          {t(
            "RFC 6901-style pointers, not JSONPath. Input replaces an existing string leaf; paths are never trimmed or created. Every QA input is preflighted on freeze; expected answers are not sent. Output existence is not verified without a real response.",
            "使用 RFC 6901 风格指针，不是 JSONPath。输入必须指向已存在的字符串字段，路径不去除空格、不自动创建。冻结时逐条预检全部 Q，不发送预期答案；没有真实响应，不能证明输出路径存在。",
          )}
        </p>
        {versionsLoaded && versions.length === 0 && (
          <Link
            href="/workspace/component-tests"
            className="block text-sm underline"
          >
            {t(
              "No request versions. Import cURL in the debugger and explicitly save an encrypted version first.",
              "暂无请求版本：先到接口调试器导入 cURL，并明确保存加密版本。",
            )}
          </Link>
        )}
        <h3 className="text-sm font-medium">
          {t("3. Bound the future workload", "3. 限定未来执行负载")}
        </h3>
        <div className="grid min-w-0 gap-4 md:grid-cols-2 xl:grid-cols-3">
          <label className="block space-y-1 text-sm">
            <span>{t("Evaluation mode", "评测模式")}</span>
            <select
              className={selectStyle}
              value={form.mode}
              onChange={(e) =>
                edit({ mode: e.target.value as PlanForm["mode"] })
              }
            >
              <option value="effectiveness">
                {t("Effectiveness — all samples once", "效果 — 全量样本一次")}
              </option>
              <option value="performance">
                {t(
                  "Performance — bounded cyclic coverage",
                  "性能 — 有界循环覆盖",
                )}
              </option>
            </select>
          </label>
          <label className="block space-y-1 text-sm">
            <span>{t("Concurrency", "并发数")}</span>
            <Input
              inputMode="numeric"
              aria-label={t("Concurrency", "并发数")}
              value={form.concurrency}
              onChange={(e) => edit({ concurrency: e.target.value })}
            />
            <span className="text-muted-foreground text-xs">
              {form.mode === "effectiveness" ? "1–8" : "1–64"}
            </span>
          </label>
          {form.mode === "performance" ? (
            <label className="block space-y-1 text-sm">
              <span>{t("Request count", "请求总数")}</span>
              <Input
                inputMode="numeric"
                aria-label={t("Request count", "请求总数")}
                value={form.requestCount}
                onChange={(e) => edit({ requestCount: e.target.value })}
              />
              <span className="text-muted-foreground text-xs">
                {t(
                  "At least every sample; up to 10000",
                  "至少覆盖全部样本，最多 10000",
                )}
              </span>
            </label>
          ) : (
            <p className="text-sm">
              {t("Request count: all samples once", "请求总数：全部样本一次")} ·{" "}
              {dataset?.sample_count ?? "—"}
            </p>
          )}
          {(
            [
              ["timeoutMs", "Request timeout (ms)", "单请求超时 (ms)"],
              ["wallTimeMs", "Total time limit (ms)", "总时限 (ms)"],
              [
                "maxTotalBodyBytes",
                "Total request-body budget (bytes)",
                "请求正文总预算 (bytes)",
              ],
            ] as const
          ).map(([key, en, cn]) => (
            <label key={key} className="block space-y-1 text-sm">
              <span>{t(en, cn)}</span>
              <Input
                inputMode="numeric"
                value={form[key]}
                onChange={(e) => edit({ [key]: e.target.value })}
              />
            </label>
          ))}
        </div>
        <p className="text-muted-foreground text-xs">
          {t(
            "Timeout: 100–300000 ms. Total: timeout–3600000 ms, not a completion guarantee. Request bodies: 1–67108864 bytes. Performance cycles samples in ascending sample ID; neither mode has an automatic PASS policy.",
            "超时 100–300000 ms；总时限不短于超时且最多 3600000 ms，不保证全部完成；正文 1–67108864 bytes。性能按样本 ID 升序循环，两种模式均不自动判为通过。",
          )}
        </p>
        {request && dataset && (
          <div className="min-w-0 space-y-2 rounded-lg border p-3 text-xs break-all">
            <p>
              {t(
                "Selected request ID / protected hash",
                "已选请求 ID / 受保护摘要",
              )}
              : {request.id} / {request.protected_hash}
            </p>
            <p>
              {t(
                "Selected dataset revision / hash",
                "已选数据 revision / hash",
              )}
              : {dataset.id} · r{dataset.revision} / {dataset.content_hash}
            </p>
            <p>
              {t("Source purpose / sample count", "数据用途 / 样本数")}:{" "}
              {dataset.purpose} / {dataset.sample_count}
            </p>
            <p>
              {t(
                "No plaintext request or gold answers are loaded here. Changing any setting revokes confirmation.",
                "此处不加载完整请求或金标。修改任意设置都会撤销确认。",
              )}
            </p>
          </div>
        )}
        {!preview && (
          <p className="text-muted-foreground text-sm">
            {t(
              "Select both versions and complete valid mappings, label and limits before freezing.",
              "请选择两个版本并填写有效映射、名称和参数后再冻结。",
            )}
          </p>
        )}
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            className="mt-1"
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
          />
          <span>
            {t(
              "I confirm freezing this definition only, not execution approval or an evaluation result. Preflight may decrypt the selected request internally and write an audit; no target call is made.",
              "我仅确认冻结此定义，不是执行批准或评测结论。预检可能在服务端内部解密选定请求并记录审计，不调用目标接口。",
            )}
          </span>
        </label>
        <Button
          disabled={!preview || !confirmed || writeBlocked}
          onClick={() => {
            if (!confirmed || writeBlocked || !preview) return;
            const payload = buildPlanPayload(
              form,
              projectId,
              componentId,
              request,
              dataset,
              confirmed,
            );
            void operate(async (token) => {
              const saved = await evaluationApi<FrozenPlan>(
                base +
                  "/components/" +
                  encodeURIComponent(componentId) +
                  "/plans",
                payload,
              );
              if (token !== epoch.current) return;
              setPlans((rows) => [
                ...rows.filter((row) => row.id !== saved.id),
                saved,
              ]);
              setForm((current) => ({ ...current, versionLabel: "" }));
              setNotice(
                t(
                  "Definition frozen — not execution approval, a target call, or a test result.",
                  "定义已冻结 — 不代表执行批准、接口已调用或评测通过。",
                ),
              );
            }, true);
          }}
        >
          {t("Freeze plan definition", "冻结计划定义")}
        </Button>
      </fieldset>
      {plans.length > 0 && (
        <section
          aria-label={t("Saved plan versions", "已保存计划版本")}
          className="min-w-0 space-y-3"
        >
          <h3 className="text-sm font-medium">
            {t(
              "Saved plan versions — definition only",
              "已保存计划版本 — 仅定义",
            )}
          </h3>
          {plans.map((row) => (
            <article
              key={row.id}
              className="min-w-0 space-y-2 rounded-lg border p-4 text-sm"
            >
              <h4 className="font-medium break-all">{row.version_label}</h4>
              <p>
                {row.definition.limits.mode} ·{" "}
                {row.definition.preflight.sample_count} {t("samples", "条样本")}{" "}
                · {row.definition.preflight.request_count}{" "}
                {t("requests", "次请求")} ·{" "}
                {row.definition.preflight.total_body_bytes} bytes
              </p>
              <p className="text-muted-foreground text-xs">
                {t(
                  "Preflight counts only; no requests were sent and no quality score exists.",
                  "仅预检统计，未发送请求、无效果得分。",
                )}
              </p>
              <details className="min-w-0 text-xs break-all">
                <summary className="cursor-pointer py-2">
                  {t("Inspect frozen settings", "查看冻结设置")}
                </summary>
                <dl className="space-y-2 leading-5">
                  {(
                    [
                      [
                        t("Plan ID / hash", "计划 ID / hash"),
                        row.id + " / " + row.definition_hash,
                      ],
                      [
                        t(
                          "Request ID / protected hash",
                          "请求 ID / 受保护摘要",
                        ),
                        row.request_version_id +
                          " / " +
                          row.definition.request_protected_hash,
                      ],
                      [
                        t(
                          "QA revision / hash / purpose",
                          "QA revision / hash / 用途",
                        ),
                        row.dataset_id +
                          " · r" +
                          row.definition.dataset_revision +
                          " / " +
                          row.definition.dataset_hash +
                          " / " +
                          row.definition.dataset_purpose,
                      ],
                      [
                        t("Input / output pointer", "输入 / 输出指针"),
                        row.definition.binding.input_pointer +
                          " / " +
                          (row.definition.binding.output_pointer ||
                            t("JSON root string", "JSON 根字符串")),
                      ],
                      [
                        t(
                          "Concurrency / timeout / total time",
                          "并发 / 超时 / 总时限",
                        ),
                        row.definition.limits.concurrency +
                          " / " +
                          row.definition.limits.timeout_ms +
                          " ms / " +
                          row.definition.limits.wall_time_ms +
                          " ms",
                      ],
                      [
                        t("Request-body budget", "请求正文预算"),
                        row.definition.limits.max_total_body_bytes + " bytes",
                      ],
                      [
                        t("Sample order", "样本顺序"),
                        row.definition.sample_order,
                      ],
                      [
                        t("Review policy", "复核策略"),
                        row.definition.evaluation_policy,
                      ],
                      [
                        t("Created / actor", "创建时间 / 操作者"),
                        row.created_at + " / " + row.created_by,
                      ],
                    ] as const
                  ).map(([label, value]) => (
                    <div key={label}>
                      <dt className="text-muted-foreground">{label}</dt>
                      <dd className="whitespace-pre-wrap">{value}</dd>
                    </div>
                  ))}
                </dl>
              </details>
            </article>
          ))}
        </section>
      )}
    </section>
  );
}

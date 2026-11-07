"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type {
  ComponentInventory,
  ComponentKind,
  ProjectComponent,
  SubmissionInventory,
} from "@/core/datasets/registry-types";
import type { DatasetVersion } from "@/core/datasets/types";
import { evaluationApi } from "@/core/evaluation/api";

const selectStyle =
  "bg-background w-full min-w-0 rounded-md border px-3 py-2 text-sm";

export function ProjectRegistryPanel({
  projectId,
  zh,
}: {
  projectId: string;
  zh: boolean;
}) {
  const [candidates, setCandidates] = useState<ComponentInventory[]>([]);
  const [components, setComponents] = useState<ProjectComponent[]>([]);
  const [datasets, setDatasets] = useState<DatasetVersion[]>([]);
  const [submissions, setSubmissions] = useState<SubmissionInventory[]>([]);
  const [sourceId, setSourceId] = useState("");
  const [kind, setKind] = useState<ComponentKind>("llm");
  const [componentId, setComponentId] = useState("");
  const [datasetId, setDatasetId] = useState("");
  const [version, setVersion] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const active = useRef(true);
  const lock = useRef(false);
  const base = `evaluation/projects/${encodeURIComponent(projectId)}`;
  const component = components.find((row) => row.id === componentId);
  const candidate = candidates.find(
    (row) => row.source_component_id === component?.source_component_id,
  );
  const dataset = datasets.find(
    (row) => row.id === datasetId && row.status === "frozen",
  );

  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);

  async function operate(action: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    setConfirmed(false);
    try {
      await action();
    } catch {
      if (active.current)
        setError(
          zh
            ? "操作失败：可能是权限、服务不可用、重复版本或快照过期。请重新加载并确认，不会自动重试写入。"
            : "Operation failed: permissions, persistence, duplicate version or stale snapshot. Reload and confirm again; writes are not retried automatically.",
        );
    } finally {
      lock.current = false;
      if (active.current) setBusy(false);
    }
  }

  async function reload() {
    setLoaded(false);
    setComponentId("");
    setDatasetId("");
    setSourceId("");
    setVersion("");
    setSubmissions([]);
    setCandidates([]);
    setComponents([]);
    setDatasets([]);
    const [sources, links, data] = await Promise.all([
      evaluationApi<{ components: ComponentInventory[] }>(
        `${base}/component-candidates`,
      ),
      evaluationApi<{ components: ProjectComponent[] }>(`${base}/components`),
      evaluationApi<{ datasets: DatasetVersion[] }>(`${base}/datasets`),
    ]);
    if (!active.current) return;
    setCandidates(sources.components);
    setComponents(links.components);
    setDatasets(data.datasets);
    setLoaded(true);
  }

  return (
    <section
      aria-label={
        zh ? "项目组件与提测版本" : "Project components & submissions"
      }
      className="min-w-0 space-y-4 rounded-xl border p-5"
    >
      <h2 className="font-semibold">
        {zh ? "项目组件与提测版本" : "Project components & submissions"}
      </h2>
      <p className="text-muted-foreground text-sm leading-6">
        {zh
          ? "将本人已登记组件加入项目，再绑定同项目已冻结的 QA 数据版本。保存的是不可变清单快照，不保存接口地址、密钥、请求体或金标；不代表请求配置已锁定、curl 已验证或评测已执行。一个项目支持多个组件，每个组件支持多个提测版本。"
          : "Link your registered components, then bind a frozen QA dataset from this project. Immutable inventory snapshots exclude endpoints, credentials, bodies and gold answers. They do not lock request configuration, verify cURL or run evaluations. Projects support multiple components and versions."}
      </p>
      <Button
        variant="outline"
        disabled={busy}
        onClick={() => void operate(reload)}
      >
        {zh ? "加载 / 刷新项目清单" : "Load / refresh registry"}
      </Button>
      {error && (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      )}
      {!loaded && !error && (
        <p className="text-muted-foreground text-sm">
          {zh
            ? "请加载清单；新冻结数据后也需刷新。"
            : "Load the registry; refresh after freezing new data."}
        </p>
      )}
      <fieldset
        disabled={busy || !loaded}
        className="grid min-w-0 gap-5 lg:grid-cols-2"
      >
        <section className="min-w-0 space-y-3 rounded-lg border p-4">
          <h3 className="font-medium">
            {zh ? "1. 加入已有组件" : "1. Link a registered component"}
          </h3>
          <label className="block space-y-1 text-sm">
            <span>{zh ? "已登记组件" : "Registered component"}</span>
            <select
              className={selectStyle}
              value={sourceId}
              onChange={(event) => setSourceId(event.target.value)}
            >
              <option value="">{zh ? "请选择" : "Select a component"}</option>
              {candidates.map((row) => (
                <option
                  key={row.source_component_id}
                  value={row.source_component_id}
                >
                  {row.name} · {row.source_component_id}
                </option>
              ))}
            </select>
          </label>
          <label className="block space-y-1 text-sm">
            <span>{zh ? "组件类型" : "Component kind"}</span>
            <select
              className={selectStyle}
              value={kind}
              onChange={(event) => setKind(event.target.value as ComponentKind)}
            >
              <option value="llm">LLM</option>
              <option value="cv">CV</option>
              <option value="agent">Agent</option>
              <option value="model">
                {zh ? "自研 / 其他模型" : "Custom / other model"}
              </option>
            </select>
          </label>
          <Button
            disabled={!sourceId}
            onClick={() =>
              void operate(async () => {
                const linked = await evaluationApi<ProjectComponent>(
                  `${base}/components`,
                  { source_component_id: sourceId, kind },
                );
                if (!active.current) return;
                setComponents((rows) => [...rows, linked]);
                setComponentId(linked.id);
                setSourceId("");
                setSubmissions([]);
                setVersion("");
                setDatasetId("");
              })
            }
          >
            {zh ? "加入项目" : "Link to project"}
          </Button>
          {loaded && candidates.length === 0 && (
            <p className="text-muted-foreground text-sm">
              {zh
                ? "暂无本人已登记组件；先到组件测试页登记。"
                : "No registered components. Register one on the component testing page first."}
            </p>
          )}
          <Link
            href="/workspace/component-tests"
            className="block text-sm underline"
          >
            {zh
              ? "前往组件登记 / 接口调试"
              : "Open registration / request debugger"}
          </Link>
        </section>
        <section className="min-w-0 space-y-3 rounded-lg border p-4">
          <h3 className="font-medium">
            {zh ? "2. 固定提测清单" : "2. Pin a submission inventory"}
          </h3>
          <label className="block space-y-1 text-sm">
            <span>{zh ? "项目组件" : "Project component"}</span>
            <select
              className={selectStyle}
              value={componentId}
              onChange={(event) => {
                const id = event.target.value;
                setComponentId(id);
                setSubmissions([]);
                setConfirmed(false);
                setVersion("");
                setDatasetId("");
                if (id)
                  void operate(async () => {
                    const result = await evaluationApi<{
                      submissions: SubmissionInventory[];
                    }>(
                      `${base}/components/${encodeURIComponent(id)}/submissions`,
                    );
                    if (active.current) setSubmissions(result.submissions);
                  });
              }}
            >
              <option value="">
                {zh ? "请选择" : "Select a project component"}
              </option>
              {components.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.name_at_link} · {row.kind}
                </option>
              ))}
            </select>
          </label>
          <label className="block space-y-1 text-sm">
            <span>{zh ? "提测版本" : "Submission version"}</span>
            <Input
              value={version}
              maxLength={80}
              onChange={(event) => {
                setVersion(event.target.value);
                setConfirmed(false);
              }}
              placeholder="v1"
            />
          </label>
          <label className="block space-y-1 text-sm">
            <span>{zh ? "已冻结数据集" : "Frozen dataset"}</span>
            <select
              className={selectStyle}
              value={datasetId}
              onChange={(event) => {
                setDatasetId(event.target.value);
                setConfirmed(false);
              }}
            >
              <option value="">
                {zh ? "请选择已冻结版本" : "Select a frozen version"}
              </option>
              {datasets
                .filter((row) => row.status === "frozen")
                .map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.name} · r{row.revision} · {row.purpose}
                  </option>
                ))}
            </select>
          </label>
          {candidate && (
            <p className="text-muted-foreground text-xs break-all">
              {candidate.name} · {candidate.transport} ·{" "}
              {candidate.response_mode} ·{" "}
              {zh ? "声明流式能力" : "Declared streaming"}:{" "}
              {String(candidate.supports_streaming)}
              <br />
              {candidate.component_fingerprint}
            </p>
          )}
          {dataset && (
            <p className="text-muted-foreground text-xs break-all">
              {dataset.name} · r{dataset.revision}
              <br />
              {dataset.content_hash}
            </p>
          )}
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-1"
              checked={confirmed}
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            <span>
              {zh
                ? "我确认上述清单与数据版本关联；这不是可执行计划或验收通过。"
                : "I confirm this inventory/data binding; it is not an executable plan or acceptance."}
            </span>
          </label>
          <Button
            disabled={
              !component ||
              !candidate ||
              !dataset?.content_hash ||
              !version.trim() ||
              !confirmed
            }
            onClick={() => {
              if (
                !component ||
                !candidate ||
                !dataset?.content_hash ||
                !confirmed
              )
                return;
              const payload = {
                version_label: version.trim(),
                dataset_id: dataset.id,
                dataset_revision: dataset.revision,
                dataset_hash: dataset.content_hash,
                component_fingerprint: candidate.component_fingerprint,
                confirmed: true,
              };
              void operate(async () => {
                const result = await evaluationApi<SubmissionInventory>(
                  `${base}/components/${encodeURIComponent(component.id)}/submissions`,
                  payload,
                );
                if (active.current) setSubmissions((rows) => [...rows, result]);
              });
            }}
          >
            {zh ? "创建不可变清单版本" : "Create immutable inventory version"}
          </Button>
        </section>
      </fieldset>
      {submissions.length > 0 && (
        <ul className="space-y-3">
          {submissions.map((row) => (
            <li
              key={row.id}
              className="min-w-0 space-y-2 rounded-lg border p-4 text-sm"
            >
              <h3 className="font-medium">{row.version_label}</h3>
              <p>
                {zh
                  ? "仅清单快照 — 不是可执行计划"
                  : "Inventory only — not an executable plan"}
              </p>
              <p>
                {row.component_snapshot.name} · {row.component_snapshot.kind} ·{" "}
                {row.dataset_purpose}
              </p>
              <dl className="space-y-1 text-xs break-all">
                <div>
                  <dt>{zh ? "提测 ID / hash" : "Submission ID / hash"}</dt>
                  <dd>
                    {row.id} / {row.submission_hash}
                  </dd>
                </div>
                <div>
                  <dt>{zh ? "数据版本 / hash" : "Dataset version / hash"}</dt>
                  <dd>
                    {row.dataset_id} · r{row.dataset_revision} /{" "}
                    {row.dataset_hash}
                  </dd>
                </div>
                <div>
                  <dt>{zh ? "创建时间 / 操作者" : "Created / actor"}</dt>
                  <dd>
                    {row.created_at} / {row.created_by}
                  </dd>
                </div>
              </dl>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

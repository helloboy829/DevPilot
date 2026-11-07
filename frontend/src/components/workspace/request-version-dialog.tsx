"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import type { ProjectComponent } from "@/core/datasets/registry-types";
import type { EvaluationProject } from "@/core/datasets/types";
import { evaluationApi } from "@/core/evaluation/api";
import type {
  RequestDefinition,
  RequestVersionMetadata,
} from "@/core/evaluation/request-version-types";

const selectStyle =
  "bg-background block w-full min-w-0 rounded-md border px-3 py-2 text-sm";

/** A mount is one reviewed request snapshot. No browser persistence or plaintext read. */
export function RequestVersionDialog({
  request,
  zh,
  onClose,
}: {
  request: RequestDefinition | null;
  zh: boolean;
  onClose: () => void;
}) {
  const formId = useId();
  const [projects, setProjects] = useState<EvaluationProject[]>([]);
  const [components, setComponents] = useState<ProjectComponent[]>([]);
  const [projectId, setProjectId] = useState("");
  const [componentId, setComponentId] = useState("");
  const [label, setLabel] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [versions, setVersions] = useState<RequestVersionMetadata[]>([]);
  const [projectsLoaded, setProjectsLoaded] = useState(false);
  const [componentsLoaded, setComponentsLoaded] = useState(false);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const lock = useRef(false);
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);

  function resetReview() {
    setConfirmed(false);
    setSaved(false);
    setError("");
  }
  function resetScope() {
    resetReview();
    setComponentId("");
    setLabel("");
    setVersions([]);
    setHistoryLoaded(false);
  }
  async function operate(action: () => Promise<void>, writing = false) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    resetReview();
    try {
      await action();
    } catch {
      if (active.current)
        setError(
          writing
            ? zh
              ? "保存未确认：请检查权限、重复标签及服务端请求加密密钥配置。输入已保留；先加载版本核对是否已保存，再重新确认重试，不会自动重试。"
              : "Could not save or confirm the result. Check permissions, duplicate labels and the server request-encryption key. Input is retained; load saved versions before confirming a retry. No automatic retries."
            : zh
              ? "加载失败，请检查权限或服务状态后重试；未发起组件调用。"
              : "Could not load. Check permissions or service availability; no component request was sent.",
        );
    } finally {
      lock.current = false;
      if (active.current) setBusy(false);
    }
  }
  async function loadProjects() {
    setProjectsLoaded(false);
    setComponentsLoaded(false);
    setProjectId("");
    setProjects([]);
    setComponents([]);
    resetScope();
    const data = await evaluationApi<{ projects: EvaluationProject[] }>(
      "evaluation/projects",
    );
    if (active.current) {
      setProjects(data.projects);
      setProjectsLoaded(true);
    }
  }
  function selectProject(value: string) {
    if (lock.current) return;
    const id = projects.some((row) => row.id === value) ? value : "";
    setProjectId(id);
    setComponents([]);
    setComponentsLoaded(false);
    resetScope();
    if (!id) return;
    void operate(async () => {
      const data = await evaluationApi<{ components: ProjectComponent[] }>(
        "evaluation/projects/" + encodeURIComponent(id) + "/components",
      );
      if (active.current) {
        setComponents(data.components);
        setComponentsLoaded(true);
      }
    });
  }
  const base =
    "evaluation/projects/" +
    encodeURIComponent(projectId) +
    "/components/" +
    encodeURIComponent(componentId) +
    "/request-versions";
  const validScope =
    projects.some((row) => row.id === projectId) &&
    components.some((row) => row.id === componentId);
  const validLabel =
    label.trim().length > 0 && label.length <= 80 && !/\p{C}/u.test(label);
  const inScope = (row: RequestVersionMetadata) =>
    row.project_id === projectId &&
    row.component_id === componentId &&
    row.scope === "request_definition_only";
  async function loadVersions() {
    if (!validScope) return;
    setVersions([]);
    setHistoryLoaded(false);
    const data = await evaluationApi<{
      request_versions: RequestVersionMetadata[];
    }>(base);
    if (active.current) {
      setVersions(data.request_versions.filter(inScope));
      setHistoryLoaded(true);
    }
  }
  async function save() {
    if (!request || !validScope || !validLabel || !confirmed || lock.current)
      return;
    await operate(async () => {
      const row = await evaluationApi<RequestVersionMetadata>(base, {
        version_label: label,
        confirmed: true,
        request,
      });
      if (!inScope(row)) throw new Error("Invalid metadata scope");
      if (active.current) {
        setVersions((previous) => [
          ...previous.filter((item) => item.id !== row.id),
          row,
        ]);
        setSaved(true);
      }
    }, true);
  }

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !lock.current) onClose();
      }}
    >
      <DialogContent
        className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl"
        aria-busy={busy}
      >
        <DialogHeader>
          <DialogTitle>
            {request
              ? zh
                ? "保存请求版本"
                : "Save request version"
              : zh
                ? "已保存的请求版本"
                : "Saved request versions"}
          </DialogTitle>
          <DialogDescription>
            {zh
              ? "完整 URL、全部头值及请求体只会在明确确认后加密保存；列表只返回元数据。保存不代表已调通、执行批准或正式评测证据。"
              : "Full URL, all header values and body are encrypted only after confirmation; lists return metadata only. Saving is not execution approval, successful debugging or evaluation evidence."}
          </DialogDescription>
        </DialogHeader>
        <p className="text-muted-foreground text-sm">
          {zh
            ? "服务端须由运维配置独立的请求加密密钥；缺少密钥时保存会被拒绝，已有元数据仍可读取。标签中请勿填写凭据或业务数据。"
            : "An operator must configure a separate request-encryption key on the server. Missing keys disable saving, not metadata reads. Do not put credentials or business data in version labels."}{" "}
          <Link
            className="underline"
            href="/workspace/datasets"
            onClick={(event) => {
              if (lock.current) event.preventDefault();
            }}
          >
            {zh ? "管理项目与组件" : "Manage projects and components"}
          </Link>
        </p>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <fieldset disabled={busy} className="min-w-0 space-y-4">
            <Button
              type="button"
              variant="outline"
              onClick={() => void operate(loadProjects)}
            >
              {zh ? "加载 / 刷新项目" : "Load / refresh projects"}
            </Button>
            {projectsLoaded && projects.length === 0 && (
              <p className="text-sm">
                {zh
                  ? "尚无项目，请先创建项目并关联组件。"
                  : "No projects yet. Create a project and link a component first."}
              </p>
            )}
            <label
              htmlFor={formId + "-project"}
              className="block space-y-1 text-sm"
            >
              <span>{zh ? "项目" : "Project"}</span>
              <select
                id={formId + "-project"}
                className={selectStyle}
                value={projectId}
                disabled={!projectsLoaded}
                onChange={(event) => selectProject(event.target.value)}
              >
                <option value="">{zh ? "选择项目" : "Select a project"}</option>
                {projects.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.name}
                  </option>
                ))}
              </select>
            </label>
            <label
              htmlFor={formId + "-component"}
              className="block space-y-1 text-sm"
            >
              <span>{zh ? "项目组件" : "Project component"}</span>
              <select
                id={formId + "-component"}
                className={selectStyle}
                value={componentId}
                disabled={!componentsLoaded}
                onChange={(event) => {
                  if (lock.current) return;
                  resetScope();
                  setComponentId(
                    components.some((row) => row.id === event.target.value)
                      ? event.target.value
                      : "",
                  );
                }}
              >
                <option value="">
                  {zh ? "选择组件" : "Select a component"}
                </option>
                {components.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.name_at_link} · {row.kind} · {row.id}
                  </option>
                ))}
              </select>
            </label>
            {componentsLoaded && components.length === 0 && (
              <p className="text-sm">
                {zh
                  ? "该项目尚未关联组件，请先在 QA 数据页面关联。"
                  : "This project has no linked components. Link one on the QA data page first."}
              </p>
            )}
            <Button
              type="button"
              variant="outline"
              disabled={!validScope}
              onClick={() => void operate(loadVersions)}
            >
              {zh ? "加载已保存版本" : "Load saved versions"}
            </Button>
            {request && (
              <div className="space-y-3 rounded-lg border p-3">
                <p className="text-sm">
                  {zh
                    ? "保存当前已编辑请求的快照；不保存响应、不发送请求。返回编辑器修改后须重新确认。"
                    : "Save a snapshot of the current edited request; no response is stored and no request is sent. Return to the editor to change it and confirm again."}
                </p>
                <label
                  htmlFor={formId + "-label"}
                  className="block space-y-1 text-sm"
                >
                  <span>{zh ? "请求版本标签" : "Request version label"}</span>
                  <Input
                    id={formId + "-label"}
                    value={label}
                    maxLength={80}
                    autoComplete="off"
                    spellCheck={false}
                    onChange={(event) => {
                      setLabel(event.target.value);
                      resetReview();
                    }}
                  />
                </label>
                <label className="flex items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={confirmed}
                    onChange={(event) => setConfirmed(event.target.checked)}
                  />
                  {zh
                    ? "我确认将当前完整请求（可能包含凭据）加密保存到所选项目组件；标签不含敏感信息。此确认不授权网络执行。"
                    : "I confirm encrypted storage of this complete request, including any credentials, under the selected project component; the label contains no sensitive data. This does not authorize network execution."}
                </label>
                <Button
                  type="submit"
                  disabled={!validScope || !validLabel || !confirmed}
                >
                  {zh ? "加密保存版本" : "Save encrypted version"}
                </Button>
              </div>
            )}
          </fieldset>
        </form>
        {error && (
          <p role="alert" className="text-destructive text-sm">
            {error}
          </p>
        )}
        {saved && (
          <p role="status" className="text-sm">
            {zh
              ? "请求版本已保存（仅定义，不代表调通或评测通过）。"
              : "Request version saved: definition only, not a successful test or evaluation."}
          </p>
        )}
        {(versions.length > 0 || historyLoaded) && (
          <section
            aria-label={zh ? "请求版本元数据" : "Request version metadata"}
            className="min-w-0 space-y-3"
          >
            <h3 className="font-medium">
              {zh ? "请求版本元数据" : "Request version metadata"}
            </h3>
            {!historyLoaded && (
              <p className="text-muted-foreground text-sm">
                {zh
                  ? "当前仅展示本次保存的版本；加载版本可查看完整清单。"
                  : "Showing versions saved in this dialog; load saved versions for the full list."}
              </p>
            )}
            {historyLoaded && versions.length === 0 && (
              <p className="text-sm">
                {zh ? "尚无已保存版本。" : "No saved versions."}
              </p>
            )}
            <ul className="space-y-2">
              {versions.map((row) => (
                <li
                  key={row.id}
                  className="space-y-2 rounded-lg border p-3 text-sm break-words"
                >
                  <strong>{row.version_label}</strong>
                  <div>
                    {row.request_template.method} ·{" "}
                    <span>{row.request_template.origin}</span>
                  </div>
                  <div>
                    {zh ? "保存时间" : "Created"}: <time>{row.created_at}</time>
                  </div>
                  <details>
                    <summary>
                      {zh
                        ? "查看结构与摘要（无请求值）"
                        : "Structure and digests (no request values)"}
                    </summary>
                    <dl className="space-y-2 pt-2">
                      <dt>{zh ? "版本 ID" : "Version ID"}</dt>
                      <dd className="break-all">{row.id}</dd>
                      <dt>{zh ? "范围" : "Scope"}</dt>
                      <dd>{row.scope}</dd>
                      <dt>{zh ? "请求头名称" : "Header names"}</dt>
                      <dd>
                        {row.request_template.headers
                          .map(([name]) => name)
                          .join(", ") || "—"}
                      </dd>
                      <dt>{zh ? "结构指纹" : "Structural fingerprint"}</dt>
                      <dd className="break-all">
                        {row.request_template.fingerprint}
                      </dd>
                      <dt>
                        {zh
                          ? "密文摘要（不是签名）"
                          : "Ciphertext digest (not a signature)"}
                      </dt>
                      <dd className="break-all">{row.protected_hash}</dd>
                    </dl>
                  </details>
                </li>
              ))}
            </ul>
          </section>
        )}
        <Button
          type="button"
          variant="outline"
          disabled={busy}
          onClick={onClose}
        >
          {zh ? "完成" : "Done"}
        </Button>
      </DialogContent>
    </Dialog>
  );
}

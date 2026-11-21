"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import {
  getMaterialBatch,
  listMaterialBatches,
} from "@/core/evaluation/material-batches";
import type {
  MaterialBatchDetail,
  MaterialBatchSummary,
} from "@/core/evaluation/material-batches";
import { useI18n } from "@/core/i18n/hooks";

function formatDate(value: string, locale: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat(locale, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
}

export default function MaterialBatchesPage() {
  const { locale } = useI18n();
  const zh = locale === "zh-CN";
  const [batches, setBatches] = useState<MaterialBatchSummary[]>([]);
  const [selected, setSelected] = useState<MaterialBatchDetail | null>(null);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestEpoch = useRef(0);

  const loadBatches = useCallback(async () => {
    setLoadingList(true);
    setError(null);
    try {
      const result = await listMaterialBatches();
      setBatches(result.batches);
    } catch {
      setError(
        zh
          ? "无法加载材料批次。请检查登录状态后重试。"
          : "Could not load material batches. Check your sign-in and retry.",
      );
    } finally {
      setLoadingList(false);
    }
  }, [zh]);

  useEffect(() => {
    void loadBatches();
    return () => {
      requestEpoch.current += 1;
    };
  }, [loadBatches]);

  async function openBatch(batchId: string) {
    const epoch = ++requestEpoch.current;
    setSelected(null);
    setLoadingDetail(true);
    setError(null);
    try {
      const detail = await getMaterialBatch(batchId);
      if (epoch === requestEpoch.current) setSelected(detail);
    } catch {
      if (epoch === requestEpoch.current) {
        setError(
          zh
            ? "无法加载该批次详情。请检查权限后重试。"
            : "Could not load this batch. Check access and retry.",
        );
      }
    } finally {
      if (epoch === requestEpoch.current) setLoadingDetail(false);
    }
  }

  return (
    <WorkspaceContainer>
      <WorkspaceHeader>
        <h1 className="text-lg font-semibold">
          {zh ? "材料批次" : "Material batches"}
        </h1>
      </WorkspaceHeader>
      <WorkspaceBody className="overflow-y-auto">
        <main className="mx-auto w-full max-w-7xl space-y-5 p-4 md:p-8">
          <header className="flex flex-wrap items-end justify-between gap-3 border-b pb-4">
            <div>
              <h2 className="text-xl font-semibold">
                {zh ? "材料批次" : "Material batches"}
              </h2>
              <p className="text-muted-foreground mt-1 text-sm">
                {zh
                  ? "浏览清单组件、附件状态与授权元数据。"
                  : "Browse component manifests, attachment status and authorization metadata."}
              </p>
            </div>
            <button
              className="hover:bg-muted rounded border px-3 py-2 text-sm disabled:opacity-50"
              disabled={loadingList}
              onClick={() => void loadBatches()}
              type="button"
            >
              {loadingList
                ? zh
                  ? "加载中…"
                  : "Loading…"
                : zh
                  ? "刷新"
                  : "Refresh"}
            </button>
          </header>

          {error && (
            <p role="alert" className="text-destructive text-sm">
              {error}
            </p>
          )}

          <section aria-label={zh ? "材料批次列表" : "Material batch list"}>
            {loadingList && batches.length === 0 ? (
              <p role="status" className="text-muted-foreground py-8 text-sm">
                {zh ? "正在加载批次…" : "Loading batches…"}
              </p>
            ) : batches.length === 0 ? (
              <p className="text-muted-foreground border-y py-8 text-sm">
                {zh ? "暂无材料批次。" : "No material batches yet."}
              </p>
            ) : (
              <div className="overflow-x-auto border-y">
                <table className="w-full min-w-[640px] text-left text-sm">
                  <thead className="text-muted-foreground border-b text-xs">
                    <tr>
                      <th className="px-3 py-2 font-medium">
                        {zh ? "批次" : "Batch"}
                      </th>
                      <th className="px-3 py-2 font-medium">
                        {zh ? "状态" : "Status"}
                      </th>
                      <th className="px-3 py-2 font-medium">
                        {zh ? "组件数" : "Components"}
                      </th>
                      <th className="px-3 py-2 font-medium">
                        {zh ? "更新时间" : "Updated"}
                      </th>
                      <th className="px-3 py-2 font-medium">
                        <span className="sr-only">
                          {zh ? "操作" : "Actions"}
                        </span>
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {batches.map((batch) => (
                      <tr key={batch.id}>
                        <td className="px-3 py-3 font-medium">{batch.name}</td>
                        <td className="px-3 py-3">{batch.status}</td>
                        <td className="px-3 py-3">{batch.component_count}</td>
                        <td className="px-3 py-3">
                          {formatDate(batch.updated_at, locale)}
                        </td>
                        <td className="px-3 py-3 text-right">
                          <button
                            aria-label={`${zh ? "打开批次" : "Open batch"} ${batch.name}`}
                            className="hover:bg-muted rounded border px-3 py-1.5 text-sm"
                            onClick={() => void openBatch(batch.id)}
                            type="button"
                          >
                            {zh ? "查看" : "View"}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {loadingDetail && (
            <p role="status" className="text-muted-foreground py-4 text-sm">
              {zh ? "正在加载批次详情…" : "Loading batch details…"}
            </p>
          )}
          {selected && (
            <section
              aria-labelledby="batch-detail-heading"
              className="space-y-5 border-t pt-5"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2
                    id="batch-detail-heading"
                    className="text-lg font-semibold"
                  >
                    {selected.name}
                  </h2>
                  <p className="text-muted-foreground mt-1 text-sm">
                    {selected.status} · {selected.component_count}{" "}
                    {zh ? "个组件" : "components"} · {zh ? "更新于" : "Updated"}{" "}
                    {formatDate(selected.updated_at, locale)}
                  </p>
                </div>
                <p className="text-muted-foreground text-sm">
                  {zh ? "清单分母固定" : "Frozen denominator"}:{" "}
                  {selected.components.length} / {selected.component_count}
                </p>
              </div>

              <div className="overflow-x-auto border-y">
                <table className="w-full min-w-[720px] text-left text-sm">
                  <caption className="px-3 py-2 text-left font-medium">
                    {zh ? "组件清单" : "Component manifest"}
                  </caption>
                  <thead className="text-muted-foreground border-y text-xs">
                    <tr>
                      <th className="px-3 py-2 font-medium">
                        {zh ? "组件" : "Component"}
                      </th>
                      <th className="px-3 py-2 font-medium">
                        {zh ? "类型" : "Kind"}
                      </th>
                      <th className="px-3 py-2 font-medium">
                        {zh ? "用途" : "Purpose"}
                      </th>
                      <th className="px-3 py-2 font-medium">
                        {zh ? "状态" : "Status"}
                      </th>
                      <th className="px-3 py-2 font-medium">
                        {zh ? "附件数" : "Attachments"}
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {selected.components.map((component) => (
                      <tr key={component.component_id}>
                        <td className="px-3 py-3 font-medium">
                          {component.name}
                        </td>
                        <td className="px-3 py-3">{component.kind}</td>
                        <td className="px-3 py-3">{component.purpose}</td>
                        <td className="px-3 py-3">
                          {component.status}
                          {component.reason ? ` · ${component.reason}` : ""}
                        </td>
                        <td className="px-3 py-3">
                          {component.artifact_ids.length}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="overflow-x-auto border-y">
                <table className="w-full min-w-[900px] text-left text-sm">
                  <caption className="px-3 py-2 text-left font-medium">
                    {zh ? "附件元数据" : "Attachment metadata"}
                  </caption>
                  <thead className="text-muted-foreground border-y text-xs">
                    <tr>
                      <th className="px-3 py-2 font-medium">
                        {zh ? "文件名" : "File name"}
                      </th>
                      <th className="px-3 py-2 font-medium">
                        {zh ? "状态" : "Status"}
                      </th>
                      <th className="px-3 py-2 font-medium">
                        {zh ? "用途" : "Purpose"}
                      </th>
                      <th className="px-3 py-2 font-medium">
                        {zh ? "敏感级别" : "Sensitivity"}
                      </th>
                      <th className="px-3 py-2 font-medium">
                        {zh ? "授权依据" : "Authorization"}
                      </th>
                      <th className="px-3 py-2 font-medium">
                        {zh ? "保留至" : "Retained until"}
                      </th>
                      <th className="px-3 py-2 font-medium">
                        {zh ? "解析状态" : "Parse status"}
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {selected.artifacts.length === 0 ? (
                      <tr>
                        <td
                          className="text-muted-foreground px-3 py-4"
                          colSpan={7}
                        >
                          {zh
                            ? "此批次未声明附件。"
                            : "No attachments declared for this batch."}
                        </td>
                      </tr>
                    ) : (
                      selected.artifacts.map((artifact) => (
                        <tr key={artifact.id}>
                          <td className="px-3 py-3 font-medium">
                            {artifact.file_name}
                          </td>
                          <td className="px-3 py-3">{artifact.status}</td>
                          <td className="px-3 py-3">{artifact.purpose}</td>
                          <td className="px-3 py-3">{artifact.sensitivity}</td>
                          <td className="px-3 py-3">
                            {artifact.authorization_basis}
                          </td>
                          <td className="px-3 py-3">
                            {formatDate(artifact.retention_until, locale)}
                          </td>
                          <td className="px-3 py-3">{artifact.parse_status}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </main>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

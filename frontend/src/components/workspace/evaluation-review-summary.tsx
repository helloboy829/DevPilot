"use client";

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { EvaluationCriteriaView } from "@/components/workspace/evaluation-criteria-view";
import { evaluationApi } from "@/core/evaluation/api";
import type { ReviewSummary } from "@/core/evaluation/review-types";

/** Parent keys by project/run and invalidates on every case operation. */
export function EvaluationReviewSummary({
  projectId,
  runId,
  zh,
}: {
  projectId: string;
  runId: string;
  zh: boolean;
}) {
  const [summary, setSummary] = useState<ReviewSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const lock = useRef(false);
  const epoch = useRef(0);
  useEffect(() => {
    const lifecycle = epoch;
    return () => {
      lifecycle.current++;
    };
  }, []);
  async function load() {
    if (lock.current) return;
    lock.current = true;
    const token = epoch.current;
    setBusy(true);
    setSummary(null);
    setError(false);
    try {
      const result = await evaluationApi<ReviewSummary>(
        "evaluation/projects/" +
          encodeURIComponent(projectId) +
          "/review-runs/" +
          encodeURIComponent(runId) +
          "/summary",
      );
      if (
        result.schema !== "qa-human-summary.v1" ||
        result.project_id !== projectId ||
        result.run_id !== runId ||
        result.acceptance !== "not_approved"
      )
        throw new Error("Invalid summary receipt");
      if (token === epoch.current) setSummary(result);
    } catch {
      if (token === epoch.current) setError(true);
    } finally {
      lock.current = false;
      if (token === epoch.current) setBusy(false);
    }
  }
  const labels = {
    pass: zh ? "通过" : "Pass",
    fail: zh ? "不通过" : "Fail",
    uncertain: zh ? "待确认" : "Uncertain",
    unreviewed: zh ? "未复核" : "Unreviewed",
  };
  const blockers = {
    collection_not_finished: zh ? "采集未正常完成" : "Collection not finished",
    technical_incomplete: zh
      ? "存在无输出证据的样本"
      : "Missing collected output evidence",
    unreviewed: zh ? "尚有未复核样本" : "Unreviewed cases remain",
    uncertain: zh ? "尚有待确认结论" : "Uncertain decisions remain",
  };
  return (
    <section
      aria-label={zh ? "固定分母复核汇总" : "Fixed-denominator review summary"}
      className="space-y-3 rounded-lg border p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="font-semibold">
          {zh ? "固定分母人工通过率" : "Fixed-denominator human pass rate"}
        </h3>
        <Button
          type="button"
          variant="outline"
          disabled={busy}
          onClick={() => void load()}
        >
          {zh ? "加载 / 刷新已验证汇总" : "Load / refresh verified summary"}
        </Button>
      </div>
      <p className="text-muted-foreground text-xs">
        {zh
          ? "以冻结计划全部样本为分母，未复核、待确认和技术失败不剔除。仅按最新人工版本计数；这是读取时的快照，不代表已批准报告或最终验收。效果计划可用，性能重复请求不混算。"
          : "All frozen-plan samples remain in the denominator, including unreviewed, uncertain and technical failures. Only latest human revisions count. This is a read-time snapshot, not an approved report or acceptance verdict. Effectiveness plans only; repeated performance requests are not mixed in."}
      </p>
      {error && (
        <p role="alert" className="text-destructive text-sm">
          {zh
            ? "汇总未验证成功。请核对权限、密钥、计划类型或并发变更后手动刷新；旧数字已清除，不会退回未验证统计。"
            : "Summary verification failed. Check permissions, key, plan mode or concurrent changes before manually refreshing. Previous numbers were cleared; no unverified fallback."}
        </p>
      )}
      {summary && (
        <div className="space-y-3">
          <p className="text-sm">
            {summary.component_name} · {summary.plan_label}
          </p>
          <div className="flex flex-wrap items-baseline gap-3">
            <strong className="text-3xl tabular-nums">
              {(summary.human_pass_rate.value * 100).toFixed(2)}%
            </strong>
            <span className="text-sm tabular-nums">
              {summary.human_pass_rate.numerator} /{" "}
              {summary.human_pass_rate.denominator}
            </span>
            <span className="text-muted-foreground text-sm">
              {summary.readiness === "review_complete"
                ? zh
                  ? "复核已完成（未批准）"
                  : "Review complete (not approved)"
                : zh
                  ? "快照预览（尚不完整）"
                  : "Snapshot preview (incomplete)"}
            </span>
          </div>
          <div className="flex flex-wrap gap-3 text-sm">
            {(["pass", "fail", "uncertain", "unreviewed"] as const).map(
              (kind) => (
                <span key={kind}>
                  {labels[kind]}: {summary.counts[kind]}
                </span>
              ),
            )}
          </div>
          <p className="text-muted-foreground text-xs">
            {zh ? "已采集输出 / 其他" : "Collected output / other"}:{" "}
            {summary.technical_counts.collected} /{" "}
            {summary.technical_counts.other}
          </p>
          {summary.blockers.length > 0 && (
            <ul className="list-inside list-disc text-sm">
              {summary.blockers.map((item) => (
                <li key={item}>{blockers[item]}</li>
              ))}
            </ul>
          )}
          <EvaluationCriteriaView
            assessment={summary.criteria_evaluation}
            zh={zh}
          />
          <details className="text-muted-foreground text-xs">
            <summary>
              {zh
                ? "快照与计划标识（不是已存档报告）"
                : "Snapshot and plan identifiers (not an archived report)"}
            </summary>
            <dl className="mt-2 space-y-1 break-all">
              <dt>{zh ? "汇总快照" : "Summary snapshot"}</dt>
              <dd>{summary.summary_hash}</dd>
              <dt>{zh ? "冻结计划" : "Frozen plan"}</dt>
              <dd>{summary.plan_hash}</dd>
            </dl>
          </details>
        </div>
      )}
    </section>
  );
}

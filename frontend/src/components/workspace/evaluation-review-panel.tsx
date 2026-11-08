"use client";

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { evaluationApi } from "@/core/evaluation/api";
import type {
  ReviewCase,
  ReviewCasePage,
  ReviewDecision,
  ReviewRun,
} from "@/core/evaluation/review-types";

export function EvaluationReviewPanel({
  projectId,
  zh,
}: {
  projectId: string;
  zh: boolean;
}) {
  const [runs, setRuns] = useState<ReviewRun[]>([]);
  const [runId, setRunId] = useState("");
  const [page, setPage] = useState<ReviewCasePage | null>(null);
  const [opened, setOpened] = useState<ReviewCase | null>(null);
  const [decision, setDecision] = useState<ReviewDecision>("uncertain");
  const [note, setNote] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const lock = useRef(false);
  const epoch = useRef(0);
  const base =
    "evaluation/projects/" + encodeURIComponent(projectId) + "/review-runs";
  const runBase = base + "/" + encodeURIComponent(runId);
  const labels: Record<ReviewDecision | "unreviewed", string> = {
    pass: zh ? "通过" : "Pass",
    fail: zh ? "不通过" : "Fail",
    uncertain: zh ? "待确认" : "Uncertain",
    unreviewed: zh ? "未复核" : "Unreviewed",
  };
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
  function clearCase() {
    setOpened(null);
    setNote("");
    setDecision("uncertain");
    setBlocked(false);
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
        if (writing) setBlocked(true);
        setError(
          zh
            ? "操作未确认成功。请重新加载并核对版本、权限或存储密钥；不会自动重试，也不会覆盖旧记录。"
            : "Operation not confirmed. Explicitly reload and inspect revisions, permissions or the storage key; no automatic retry or overwrite.",
        );
      }
    } finally {
      lock.current = false;
      if (token === epoch.current) setBusy(false);
    }
  }
  async function loadRuns(token: number) {
    clearCase();
    setPage(null);
    setRunId("");
    setRuns([]);
    const result = await evaluationApi<{ runs: ReviewRun[] }>(base);
    if (token === epoch.current) {
      setRuns(result.runs);
      if (!result.runs.length)
        setNotice(
          zh
            ? "尚无派发记录。请在上方独立授权的执行面板中确认并运行冻结计划，再刷新复核列表。需运营方启用执行；本复核面板不会创建运行。"
            : "No dispatch records yet. Use the separately authorized execution panel above to confirm and run a frozen plan, then refresh review runs. Operator execution enablement is required; this review panel never creates runs.",
        );
    }
  }
  async function loadPage(token: number, offset: number) {
    clearCase();
    setPage(null);
    const result = await evaluationApi<ReviewCasePage>(
      runBase + "/cases?offset=" + offset + "&limit=100",
    );
    if (token === epoch.current) setPage(result);
  }
  async function openCase(token: number, ordinal: number) {
    clearCase();
    const result = await evaluationApi<ReviewCase>(
      runBase + "/cases/" + ordinal,
    );
    if (token === epoch.current) setOpened(result);
  }
  async function save(token: number) {
    if (!opened || !confirmed || blocked) return;
    await evaluationApi(runBase + "/cases/" + opened.ordinal + "/reviews", {
      case_hash: opened.case_hash,
      expected_revision: opened.review_revision,
      decision,
      note: note.trim(),
      confirmed: true,
    });
    if (token === epoch.current) {
      clearCase();
      setPage(null);
      setNotice(
        zh
          ? "已追加人工复核版本。请重新加载列表，查看最新记录；旧版本未被覆盖。"
          : "Human review revision appended. Reload cases to inspect the latest record; previous revisions were not overwritten.",
      );
    }
  }
  const terminal =
    opened &&
    ["observed", "delivery_unknown", "not_dispatched"].includes(opened.state);
  const canPass =
    !!opened?.evidence_hash &&
    opened.output !== null &&
    opened.technical.kind === "output_collected" &&
    opened.state === "observed";
  return (
    <section
      className="space-y-4 rounded-xl border p-5"
      aria-label={zh ? "人工结果复核" : "Human result review"}
    >
      <div>
        <h2 className="text-lg font-semibold">
          {zh ? "人工结果复核" : "Human result review"}
        </h2>
        <p className="text-muted-foreground text-sm">
          {zh
            ? "技术采集完成不代表效果通过。按组件和样本核对输入、实际输出、参考答案及来源，逐条记录人工结论。这里不启动测试、不调用模型；当前仅展示最近 200 次派发记录。"
            : "Technical completion is not quality PASS. Inspect each component's input, actual output, reference and source, then record a human decision. No test starts or model calls here; at most the latest 200 dispatch records are listed."}
        </p>
      </div>
      {error && (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="text-sm">
          {notice}
        </p>
      )}
      <fieldset disabled={busy} className="space-y-4">
        <div className="flex flex-wrap items-end gap-3">
          <Button
            type="button"
            variant="outline"
            onClick={() => void operate(loadRuns)}
          >
            {zh ? "加载 / 刷新复核运行" : "Load / refresh review runs"}
          </Button>
          <label className="min-w-48 flex-1 text-sm">
            {zh ? "复核运行" : "Review run"}
            <select
              className="bg-background mt-1 w-full rounded border p-2"
              value={runId}
              onChange={(event) => {
                setRunId(event.target.value);
                setPage(null);
                clearCase();
              }}
            >
              <option value="">
                {zh
                  ? "选择组件 / 计划 / 运行"
                  : "Select component / plan / run"}
              </option>
              {runs.map((run) => (
                <option key={run.id} value={run.id}>
                  {run.component_name} · {run.plan_label} · {run.status} ·{" "}
                  {run.id}
                </option>
              ))}
            </select>
          </label>
          <Button
            type="button"
            variant="outline"
            disabled={!runId}
            onClick={() => void operate((token) => loadPage(token, 0))}
          >
            {zh ? "加载样本列表" : "Load cases"}
          </Button>
        </div>
        {page && (
          <div className="space-y-3">
            <div className="flex flex-wrap gap-3 text-sm">
              {(["pass", "fail", "uncertain", "unreviewed"] as const).map(
                (kind) => (
                  <span key={kind}>
                    {labels[kind]}: {page.counts[kind]}
                  </span>
                ),
              )}
            </div>
            <p className="text-muted-foreground text-xs">
              {zh
                ? "以上为最新人工决策条数，不是准确率或最终验收结论；未复核样本不会被排除。"
                : "Counts are latest human decisions, not accuracy or final acceptance; unreviewed cases remain visible."}
            </p>
            <div className="max-h-72 space-y-2 overflow-auto">
              {page.cases.map((row) => (
                <Button
                  key={row.ordinal}
                  type="button"
                  variant="outline"
                  className="h-auto w-full justify-start text-left whitespace-normal"
                  onClick={() =>
                    void operate((token) => openCase(token, row.ordinal))
                  }
                  aria-label={
                    (zh ? "打开样本" : "Open case") +
                    " " +
                    row.ordinal +
                    " · " +
                    row.sample_id
                  }
                >
                  #{row.ordinal} · {row.sample_id} · {row.state} ·{" "}
                  {row.kind ?? "—"} ·{" "}
                  {row.review_decision
                    ? labels[row.review_decision]
                    : labels.unreviewed}{" "}
                  · r{row.review_revision}
                </Button>
              ))}
            </div>
            <div className="flex items-center gap-3">
              <Button
                type="button"
                variant="outline"
                disabled={page.offset === 0}
                onClick={() =>
                  void operate((token) =>
                    loadPage(token, Math.max(0, page.offset - page.limit)),
                  )
                }
              >
                {zh ? "上一页" : "Previous page"}
              </Button>
              <span className="text-sm">
                {page.offset + 1}–{page.offset + page.cases.length} /{" "}
                {page.run.request_count}
              </span>
              <Button
                type="button"
                variant="outline"
                disabled={page.offset + page.limit >= page.run.request_count}
                onClick={() =>
                  void operate((token) =>
                    loadPage(token, page.offset + page.limit),
                  )
                }
              >
                {zh ? "下一页" : "Next page"}
              </Button>
            </div>
          </div>
        )}
        {opened && (
          <div className="space-y-4 border-t pt-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h3 className="font-semibold">
                {opened.component_name} · {opened.plan_label} · #
                {opened.ordinal} · {opened.sample_id}
              </h3>
              <Button
                type="button"
                variant="outline"
                onClick={() =>
                  void operate((token) => openCase(token, opened.ordinal))
                }
              >
                {zh ? "重新加载此样本" : "Reload case"}
              </Button>
            </div>
            <p className="text-muted-foreground text-xs">
              {opened.state} · {opened.technical.kind ?? "—"} · HTTP{" "}
              {opened.technical.http_status ?? "—"} ·{" "}
              {opened.technical.elapsed_ms ?? "—"} ms · r
              {opened.review_revision}
            </p>
            <div className="grid gap-3 lg:grid-cols-3">
              {[
                [zh ? "输入问题 Q" : "Input Q", opened.input],
                [
                  zh ? "组件输出 A" : "Actual A",
                  opened.output ??
                    (zh
                      ? "没有不可变输出证据"
                      : "No immutable output evidence"),
                ],
                [
                  zh ? "预期 / 参考答案" : "Expected / reference",
                  opened.expected,
                ],
              ].map(([label, value]) => (
                <div key={label} className="min-w-0 rounded border p-3">
                  <h4 className="mb-2 text-sm font-medium">{label}</h4>
                  <pre className="max-h-80 overflow-auto font-sans text-sm break-words whitespace-pre-wrap">
                    {value}
                  </pre>
                </div>
              ))}
            </div>
            <dl className="text-muted-foreground grid gap-1 text-xs">
              <dt>
                {zh
                  ? "参考来源（文本，不自动打开）"
                  : "Reference source (text, not opened automatically)"}
              </dt>
              <dd className="break-all">{opened.source_ref}</dd>
              <dt>{zh ? "数据分层" : "Slice"}</dt>
              <dd>{opened.slice_tag}</dd>
            </dl>
            <fieldset disabled={!terminal || blocked} className="space-y-3">
              <legend className="text-sm font-medium">
                {zh ? "追加人工决策" : "Append human decision"}
              </legend>
              <div className="flex flex-wrap gap-4">
                {(["pass", "fail", "uncertain"] as const).map((value) => (
                  <label
                    key={value}
                    className="flex items-center gap-2 text-sm"
                  >
                    <input
                      type="radio"
                      name={"decision-" + projectId}
                      checked={decision === value}
                      disabled={value === "pass" && !canPass}
                      onChange={() => {
                        setDecision(value);
                        revoke();
                      }}
                    />
                    {labels[value]}
                  </label>
                ))}
              </div>
              <label className="block space-y-1 text-sm">
                <span>{zh ? "复核说明" : "Review note"}</span>
                <Textarea
                  disabled={busy || !terminal || blocked}
                  maxLength={2000}
                  value={note}
                  onChange={(event) => {
                    setNote(event.target.value);
                    revoke();
                  }}
                />
              </label>
            </fieldset>
            <label className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                checked={confirmed}
                disabled={!terminal}
                onChange={(event) => setConfirmed(event.target.checked)}
              />
              {zh
                ? "我确认此人工决策对应当前显示的样本及版本；这是追加记录，不是自动判分或最终报告审批。"
                : "I confirm this human decision applies to this displayed case and revision; it appends a record, not automated grading or final report approval."}
            </label>
            <Button
              type="button"
              disabled={
                !terminal ||
                blocked ||
                !confirmed ||
                !note.trim() ||
                (decision === "pass" && !canPass) ||
                opened.review_revision >= 100
              }
              onClick={() => void operate(save, true)}
            >
              {zh ? "保存复核新版本" : "Save review revision"}
            </Button>
            {!terminal && (
              <p className="text-sm">
                {zh
                  ? "此样本尚未终止，暂不能提交复核。"
                  : "This case is not terminal; review submission is unavailable."}
              </p>
            )}
            <div className="space-y-2">
              <h4 className="text-sm font-medium">
                {zh ? "人工复核历史" : "Human review history"}
              </h4>
              {opened.reviews.map((row) => (
                <article
                  key={row.revision}
                  className="rounded border p-3 text-sm"
                >
                  <p>
                    r{row.revision} · {labels[row.decision]} ·{" "}
                    {new Date(row.created_at_ms).toLocaleString()} ·{" "}
                    {row.reviewer_id}
                  </p>
                  <p className="mt-1 break-words whitespace-pre-wrap">
                    {row.note}
                  </p>
                </article>
              ))}
            </div>
          </div>
        )}
      </fieldset>
    </section>
  );
}

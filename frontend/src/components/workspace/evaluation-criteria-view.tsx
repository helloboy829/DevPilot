import type { CriteriaEvaluation } from "@/core/evaluation/review-types";

/** Render a server-verified frozen assessment, never infer it from rounded UI rates. */
export function EvaluationCriteriaView({
  assessment,
  zh,
}: {
  assessment?: CriteriaEvaluation;
  zh: boolean;
}) {
  const labels = {
    met: zh
      ? "效果阈值达标（未批准）"
      : "Effectiveness threshold met (not approved)",
    not_met: zh
      ? "效果阈值未达标（未批准）"
      : "Effectiveness threshold not met (not approved)",
    incomplete: zh
      ? "证据不完整，尚不能判定达标（未批准）"
      : "Incomplete evidence; no threshold verdict (not approved)",
  };
  return (
    <div className="min-w-0 space-y-1 rounded-md border p-3 text-sm break-words">
      {assessment ? (
        <>
          <p>
            {assessment.criteria.version_label} ·{" "}
            {zh ? "最低人工通过率" : "Minimum human pass rate"}:{" "}
            {(assessment.criteria.min_pass_rate_bps / 100).toFixed(2)}%
          </p>
          <p className="font-medium">{labels[assessment.status]}</p>
        </>
      ) : (
        <p>
          {zh
            ? "该运行执行前未冻结标准，不判定达标；不能事后补阈值。"
            : "No pre-run frozen criteria; no threshold verdict. Criteria cannot be added retrospectively."}
        </p>
      )}
      <p className="text-muted-foreground text-xs">
        {zh
          ? "仅效果标准，不代表性能合格或正式项目批准。"
          : "Effectiveness criteria only, not performance acceptance or formal project approval."}
      </p>
    </div>
  );
}

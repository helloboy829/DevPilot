import type { DatasetVersion } from "@/core/datasets/types";
import type { PlanCreate, PlanLimits } from "@/core/evaluation/plan-types";
import type { RequestVersionMetadata } from "@/core/evaluation/request-version-types";

export interface PlanForm {
  versionLabel: string;
  inputPointer: string;
  outputPointer: string;
  rootOutput: boolean;
  mode: PlanLimits["mode"];
  concurrency: string;
  requestCount: string;
  timeoutMs: string;
  wallTimeMs: string;
  maxTotalBodyBytes: string;
}
export function initialPlanForm(): PlanForm {
  return {
    versionLabel: "",
    inputPointer: "",
    outputPointer: "",
    rootOutput: false,
    mode: "effectiveness",
    concurrency: "1",
    requestCount: "1",
    timeoutMs: "30000",
    wallTimeMs: "300000",
    maxTotalBodyBytes: "1048576",
  };
}
function invalid(): never {
  throw new Error("Invalid plan settings");
}
function integer(value: string, min: number, max: number) {
  if (!/^(0|[1-9][0-9]*)$/.test(value)) return invalid();
  const number = Number(value);
  if (!Number.isSafeInteger(number) || number < min || number > max)
    return invalid();
  return number;
}
function pointer(value: string, input: boolean) {
  if (
    (input && !value) ||
    (value && !value.startsWith("/")) ||
    /[\x00-\x1f\x7f]/.test(value) ||
    new TextEncoder().encode(value).length > 512 ||
    /~(?![01])/.test(value) ||
    (value && value.slice(1).split("/").length > 16)
  )
    invalid();
  // TextEncoder replaces unpaired surrogates; reject rather than changing a path.
  for (const char of value) {
    const code = char.codePointAt(0)!;
    if (code >= 0xd800 && code <= 0xdfff) invalid();
  }
  return value;
}
/** UI guard only. Server rechecks owner, integrity, mapping, key and budgets. */
export function buildPlanPayload(
  form: PlanForm,
  projectId: string,
  componentId: string,
  request: RequestVersionMetadata | undefined,
  dataset: DatasetVersion | undefined,
  confirmed: boolean,
): PlanCreate {
  const id = /^[A-Za-z0-9_-]{1,64}$/;
  const hash = /^[0-9a-f]{64}$/;
  if (
    confirmed !== true ||
    !id.test(projectId) ||
    !id.test(componentId) ||
    !request ||
    !dataset ||
    request.project_id !== projectId ||
    request.component_id !== componentId ||
    dataset.project_id !== projectId ||
    request.scope !== "request_definition_only" ||
    dataset.status !== "frozen" ||
    !id.test(request.id) ||
    !id.test(dataset.id) ||
    !hash.test(request.protected_hash) ||
    !dataset.content_hash ||
    !hash.test(dataset.content_hash) ||
    !Number.isSafeInteger(dataset.revision) ||
    dataset.revision < 1 ||
    !Number.isSafeInteger(dataset.sample_count) ||
    dataset.sample_count < 1 ||
    dataset.sample_count > 500
  )
    return invalid();
  const label = form.versionLabel.trim();
  if (!label || label.length > 80 || /\p{C}/u.test(label)) return invalid();
  if (form.mode !== "effectiveness" && form.mode !== "performance")
    return invalid();
  if (!form.rootOutput && !form.outputPointer) return invalid();
  const timeout = integer(form.timeoutMs, 100, 300000);
  const wall = integer(form.wallTimeMs, 100, 3600000);
  if (wall < timeout) return invalid();
  return {
    version_label: label,
    request_version_id: request.id,
    request_protected_hash: request.protected_hash,
    dataset_id: dataset.id,
    dataset_revision: dataset.revision,
    dataset_hash: dataset.content_hash,
    binding: {
      schema: "qa-json-binding.v1",
      input_pointer: pointer(form.inputPointer, true),
      output_pointer: pointer(form.rootOutput ? "" : form.outputPointer, false),
    },
    response_mode: "json_text",
    limits: {
      mode: form.mode,
      concurrency: integer(
        form.concurrency,
        1,
        form.mode === "effectiveness" ? 8 : 64,
      ),
      request_count:
        form.mode === "effectiveness"
          ? dataset.sample_count
          : integer(form.requestCount, dataset.sample_count, 10000),
      timeout_ms: timeout,
      wall_time_ms: wall,
      max_total_body_bytes: integer(form.maxTotalBodyBytes, 1, 67108864),
    },
    confirmed: true,
  };
}

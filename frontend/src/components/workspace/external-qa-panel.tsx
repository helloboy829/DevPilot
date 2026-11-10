"use client";

import { useEffect, useRef, useState, type MutableRefObject } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { parseExportReceipt } from "@/core/evaluation/export-policy";
import { externalQAApi } from "@/core/evaluation/external-qa-api";
import {
  intakeIdValid,
  originalRunIdValid,
  inspectTechnicalPair,
  parseIntakeAudit,
  parseIntakeReceipt,
  parseIntakeSource,
  readTechnicalFile,
  type IntakeAuditEvent,
  type IntakeReceipt,
  type IntakeSource,
  type PendingIntake,
  type PendingIntakes,
  type TechnicalDocument,
} from "@/core/evaluation/external-qa-policy";

type Prepared = Awaited<ReturnType<typeof inspectTechnicalPair>>;
type Role = "receipt" | "reconciliation";
/** Parent page memory owns pending IDs and the cross-project write lock. Key by project/locale. */
export function ExternalQAPanel({
  projectId,
  zh,
  pendingIntakes,
  writeLock,
}: {
  projectId: string;
  zh: boolean;
  pendingIntakes: PendingIntakes;
  writeLock: MutableRefObject<boolean>;
}) {
  const t = (en: string, cn: string) => (zh ? cn : en);
  const base = "evaluation/projects/" + encodeURIComponent(projectId);
  const [exportId, setExportId] = useState("");
  const [source, setSource] = useState<IntakeSource | null>(null);
  const [originalId, setOriginalId] = useState("");
  const [documents, setDocuments] = useState<
    Record<Role, TechnicalDocument | null>
  >({ receipt: null, reconciliation: null });
  const [reading, setReading] = useState<Record<Role, boolean>>({
    receipt: false,
    reconciliation: false,
  });
  const [prepared, setPrepared] = useState<Prepared | null>(null);
  const [consents, setConsents] = useState([false, false, false]);
  const [pending, setPending] = useState<PendingIntake | null>(
    () => pendingIntakes.get(projectId) ?? null,
  );
  const [opened, setOpened] = useState<IntakeReceipt | null>(null);
  const [lookup, setLookup] = useState("");
  const [events, setEvents] = useState<IntakeAuditEvent[] | null>(null);
  const [cursor, setCursor] = useState<number | null>(null);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(false);
  const lock = useRef(false),
    epoch = useRef(0),
    fileTokens = useRef({ receipt: 0, reconciliation: 0 }),
    controller = useRef<AbortController | null>(null);
  useEffect(() => {
    const life = epoch,
      request = controller;
    return () => {
      life.current++;
      request.current?.abort();
    };
  }, []);
  const revoke = () => setConsents([false, false, false]);
  function clearFiles() {
    fileTokens.current.receipt++;
    fileTokens.current.reconciliation++;
    setDocuments({ receipt: null, reconciliation: null });
    setReading({ receipt: false, reconciliation: false });
    setPrepared(null);
  }
  async function operation(
    work: (current: () => boolean, signal: AbortSignal) => Promise<void>,
  ) {
    if (lock.current) return;
    lock.current = true;
    const token = epoch.current,
      current = () => epoch.current === token,
      abort = new AbortController();
    controller.current = abort;
    setBusy(true);
    setError(false);
    revoke();
    try {
      await work(current, abort.signal);
    } catch {
      if (current()) setError(true);
    } finally {
      if (controller.current === abort) controller.current = null;
      lock.current = false;
      if (current()) setBusy(false);
    }
  }
  async function selectFile(role: Role, file: File | undefined) {
    if (lock.current) return;
    const token = ++fileTokens.current[role],
      scope = epoch.current;
    const current = () =>
      scope === epoch.current && token === fileTokens.current[role];
    setDocuments((old) => ({ ...old, [role]: null }));
    setPrepared(null);
    revoke();
    setError(false);
    setReading((old) => ({ ...old, [role]: !!file }));
    if (!file) return;
    try {
      const doc = await readTechnicalFile(file);
      if (current()) setDocuments((old) => ({ ...old, [role]: doc }));
    } catch {
      if (current()) setError(true);
    } finally {
      if (current()) setReading((old) => ({ ...old, [role]: false }));
    }
  }
  async function openSource() {
    if (!intakeIdValid(exportId)) return;
    const selected = exportId;
    setSource(null);
    clearFiles();
    await operation(async (current, signal) => {
      const raw = await externalQAApi(
        base + "/exports/" + selected,
        undefined,
        signal,
      );
      if (!current()) return;
      const receipt = parseExportReceipt(raw, projectId, selected);
      if (receipt.tier !== "baseline_inputs" || !receipt.input_set_complete)
        throw Error("Incomplete historical source");
      const plan = await externalQAApi(
        base + "/plans/" + encodeURIComponent(receipt.plan_id),
        undefined,
        signal,
      );
      const checked = parseIntakeSource(raw, plan, projectId, selected);
      if (current()) setSource(checked);
    });
  }
  async function inspect() {
    if (
      !source ||
      !documents.receipt ||
      !documents.reconciliation ||
      !originalRunIdValid(originalId) ||
      reading.receipt ||
      reading.reconciliation
    )
      return;
    setPrepared(null);
    await operation(async (current) => {
      const result = await inspectTechnicalPair(
        documents.receipt!,
        documents.reconciliation!,
        originalId,
        source,
      );
      if (current()) setPrepared(result);
    });
  }
  async function finish(
    raw: unknown,
    remembered: PendingIntake,
    current: () => boolean,
  ) {
    const result = await parseIntakeReceipt(
      raw,
      projectId,
      remembered.id,
      remembered,
    );
    if (!current() || pendingIntakes.get(projectId) !== remembered) return;
    pendingIntakes.delete(projectId);
    setPending(null);
    setOpened(result);
    setLookup(result.id);
    setEvents(null);
    setCursor(null);
  }
  async function create() {
    if (
      lock.current ||
      writeLock.current ||
      pendingIntakes.has(projectId) ||
      !prepared ||
      !consents.every(Boolean) ||
      reading.receipt ||
      reading.reconciliation
    )
      return;
    const selected = prepared,
      id = crypto.randomUUID().replaceAll("-", "");
    const remembered: PendingIntake = { ...selected.expected, id, projectId };
    // Reserve before the first await. Never retain raw files or a PUT body in page-level pending state.
    pendingIntakes.set(projectId, remembered);
    setPending(remembered);
    setOpened(null);
    setEvents(null);
    setCursor(null);
    clearFiles();
    writeLock.current = true;
    try {
      await operation(async (current, signal) => {
        const raw = await externalQAApi(
          base + "/external-qa-intakes/" + id,
          selected.body,
          signal,
        );
        await finish(raw, remembered, current);
      });
    } finally {
      writeLock.current = false;
    }
  }
  async function reconcile() {
    const remembered = pendingIntakes.get(projectId);
    if (!remembered) return;
    await operation(async (current, signal) => {
      const raw = await externalQAApi(
        base + "/external-qa-intakes/" + remembered.id,
        undefined,
        signal,
      );
      await finish(raw, remembered, current);
    });
  }
  async function openHistorical() {
    if (!intakeIdValid(lookup)) return;
    const selected = lookup;
    setOpened(null);
    setEvents(null);
    setCursor(null);
    await operation(async (current, signal) => {
      const raw = await externalQAApi(
        base + "/external-qa-intakes/" + selected,
        undefined,
        signal,
      );
      const result = await parseIntakeReceipt(
        raw,
        projectId,
        selected,
        pendingIntakes.get(projectId)?.id === selected
          ? pendingIntakes.get(projectId)
          : undefined,
      );
      if (current()) setOpened(result);
    });
  }
  async function audit(more = false) {
    if (!opened || (more && cursor === null)) return;
    const selected = opened,
      after = more ? cursor! : 0;
    if (!more) {
      setEvents(null);
      setCursor(null);
    }
    await operation(async (current, signal) => {
      const page = parseIntakeAudit(
        await externalQAApi(
          base +
            "/external-qa-intakes/" +
            selected.id +
            "/audit?after_sequence=" +
            after +
            "&limit=50",
          undefined,
          signal,
        ),
        projectId,
        selected.id,
        after,
      );
      const combined = more ? [...(events ?? []), ...page.events] : page.events;
      if (new Set(combined.map((e) => e.id)).size !== combined.length)
        throw Error("Invalid audit page");
      if (current()) {
        setEvents(combined);
        setCursor(page.next_after_sequence);
      }
    });
  }
  const labels = [
    t(
      "I confirm the exact historical export and original run ID.",
      "我确认所选历史导出及原始运行 ID。",
    ),
    t(
      "I confirm these two files contain technical metadata only, not outputs, QA, keys or journals.",
      "我确认两份文件仅含技术元数据，不含输出、问答、密钥或数据库日志。",
    ),
    t(
      "I acknowledge this untrusted declaration is not evidence, approval or execution authority.",
      "我知悉不可信声明不是证据、批准或执行授权。",
    ),
  ];
  return (
    <section
      aria-label={t(
        "External QA technical quarantine",
        "外部 QA 技术声明隔离接收",
      )}
      className="min-w-0 space-y-4 rounded-xl border p-4"
    >
      <h2 className="text-lg font-semibold">
        {t("External QA technical quarantine", "外部 QA 技术声明隔离接收")}
      </h2>
      <p className="text-muted-foreground text-sm">
        {t(
          "Untrusted technical declarations only — NOT_EVALUATED. Hashes are not signatures. No output/evidence admission, approval, dispatch, resume or resend authority.",
          "仅接收不可信技术声明 — NOT_EVALUATED。哈希不是签名，不接纳输出或证据，不授予批准、派发、恢复或重发权限。",
        )}
      </p>
      {pending && (
        <div role="status" className="space-y-2 rounded-md border p-3 text-sm">
          <p className="break-all">
            {t(
              "Unresolved outcome. Original intake ID: ",
              "结果待对账。原始接收 ID：",
            )}
            {pending.id}
          </p>
          <p>
            {t(
              "Only GET this same ID, including after 404. Never resend PUT or replace the ID.",
              "包括 GET 404 在内，仅查询此原 ID；不得重发 PUT 或更换 ID。",
            )}
          </p>
          <Button
            variant="outline"
            disabled={busy}
            onClick={() => void reconcile()}
          >
            {t("Reconcile same intake ID by GET", "按原接收 ID 查询对账")}
          </Button>
        </div>
      )}
      <div className="space-y-2">
        <label className="block text-sm">
          {t("Exact historical export ID", "准确历史导出 ID")}
          <Input
            value={exportId}
            disabled={busy}
            maxLength={32}
            onChange={(e) => {
              if (lock.current) return;
              setExportId(e.target.value);
              setSource(null);
              clearFiles();
              revoke();
            }}
          />
        </label>
        <Button
          variant="outline"
          disabled={busy || !intakeIdValid(exportId)}
          onClick={() => void openSource()}
        >
          {t(
            "Open historical export and frozen plan",
            "打开历史导出及冻结计划",
          )}
        </Button>
      </div>
      {source && (
        <div className="space-y-1 text-sm">
          <h3>
            {t("Historical baseline source opened", "已打开历史基线来源")}
          </h3>
          <pre className="max-h-64 overflow-auto text-xs break-all whitespace-pre-wrap">
            {JSON.stringify(source, null, 2)}
          </pre>
        </div>
      )}
      <label className="block text-sm">
        {t("Original external run UUID", "原始外部运行 UUID")}
        <Input
          value={originalId}
          disabled={busy}
          maxLength={36}
          onChange={(e) => {
            if (lock.current) return;
            setOriginalId(e.target.value);
            setPrepared(null);
            revoke();
          }}
        />
      </label>
      <div className="grid gap-3 md:grid-cols-2">
        {(["receipt", "reconciliation"] as const).map((role) => (
          <div key={role} className="min-w-0 space-y-1">
            <label className="block text-sm">
              {role === "receipt"
                ? t("Receipt JSON file", "身份回执 JSON 文件")
                : t("Reconciliation JSON file", "对账 JSON 文件")}
              <Input
                type="file"
                accept=".json,application/json"
                disabled={busy || !source}
                onChange={(e) => {
                  const file = e.currentTarget.files?.[0];
                  e.currentTarget.value = "";
                  void selectFile(role, file);
                }}
              />
            </label>
            <p className="text-muted-foreground text-xs break-all">
              {reading[role]
                ? t("Reading bounded technical file…", "正在读取有界技术文件…")
                : documents[role]
                  ? String(documents[role].bytes) +
                    " bytes · SHA-256 " +
                    documents[role].sha256
                  : t(
                      "Choose one UTF-8 technical document, at most 8192 bytes. No outputs or journals.",
                      "显式选择一份 UTF-8 技术文件，最多 8192 字节；不要选择输出或数据库日志。",
                    )}
            </p>
          </div>
        ))}
      </div>
      <Button
        variant="outline"
        disabled={
          busy ||
          !source ||
          !documents.receipt ||
          !documents.reconciliation ||
          reading.receipt ||
          reading.reconciliation ||
          !originalRunIdValid(originalId)
        }
        onClick={() => void inspect()}
      >
        {t("Inspect selected technical documents", "校验所选技术文件")}
      </Button>
      {prepared && (
        <div className="space-y-1">
          <h3 className="text-sm">
            {t(
              "Technical inspection only — NOT_EVALUATED",
              "仅技术校验 — NOT_EVALUATED",
            )}
          </h3>
          <pre className="max-h-64 overflow-auto text-xs break-all whitespace-pre-wrap">
            {JSON.stringify(prepared.expected.inspection, null, 2)}
          </pre>
        </div>
      )}
      <fieldset disabled={busy || !prepared || !!pending} className="space-y-2">
        {labels.map((label, index) => (
          <label key={label} className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-1 shrink-0"
              checked={consents[index]}
              onChange={(e) =>
                setConsents((old) =>
                  old.map((v, i) => (i === index ? e.target.checked : v)),
                )
              }
            />
            <span>{label}</span>
          </label>
        ))}
      </fieldset>
      <Button
        disabled={
          busy ||
          writeLock.current ||
          !!pending ||
          !prepared ||
          !consents.every(Boolean)
        }
        onClick={() => void create()}
      >
        {t("Quarantine technical declarations", "隔离存档技术声明")}
      </Button>
      <div className="space-y-2 border-t pt-3">
        <label className="block text-sm">
          {t("Exact historical intake ID", "准确历史接收 ID")}
          <Input
            value={lookup}
            maxLength={32}
            disabled={busy}
            onChange={(e) => {
              if (lock.current) return;
              setLookup(e.target.value);
              setOpened(null);
              setEvents(null);
              setCursor(null);
              revoke();
            }}
          />
        </label>
        <Button
          variant="outline"
          disabled={busy || !intakeIdValid(lookup)}
          onClick={() => void openHistorical()}
        >
          {t("Open historical quarantine receipt", "打开历史隔离回执")}
        </Button>
      </div>
      {opened && (
        <div className="space-y-2">
          <h3 className="text-sm">
            {t(
              "Historical quarantine receipt — NOT_EVALUATED",
              "历史隔离回执 — NOT_EVALUATED",
            )}
          </h3>
          <pre className="max-h-80 overflow-auto text-xs break-all whitespace-pre-wrap">
            {JSON.stringify(opened, null, 2)}
          </pre>
          <p className="text-muted-foreground text-xs">
            {t(
              "Original declared byte hashes differ from canonical hashes; stored canonical validation cannot reauthenticate discarded original bytes or external delivery.",
              "原始声明字节哈希与规范化哈希分别保存；存储后校验不能重新认证已丢弃的原始字节或外部交付。",
            )}
          </p>
          <Button
            variant="outline"
            disabled={busy}
            onClick={() => void audit()}
          >
            {t("Load quarantine audit", "加载隔离审计")}
          </Button>
          {events && (
            <pre className="max-h-64 overflow-auto text-xs break-all whitespace-pre-wrap">
              {JSON.stringify(events, null, 2)}
            </pre>
          )}
          {cursor !== null && (
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => void audit(true)}
            >
              {t("Load next quarantine audit page", "加载下一页隔离审计")}
            </Button>
          )}
        </div>
      )}
      {error && (
        <p role="alert" className="text-destructive text-sm">
          {t(
            "Operation failed or outcome unknown. Check permissions and the selected technical metadata. If an intake ID is pending, only explicitly GET that same ID; never resend.",
            "操作失败或结果未知。请检查权限和所选技术元数据。若存在待对账接收 ID，仅显式查询该原 ID，不得重发。",
          )}
        </p>
      )}
    </section>
  );
}

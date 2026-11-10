"use client";

import { useEffect, useRef, useState, type MutableRefObject } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { evaluationApi } from "@/core/evaluation/api";
import { evaluationExportBundle } from "@/core/evaluation/export-download";
import {
  exportIdValid,
  parseExportAudit,
  parseExportCapabilities,
  parseExportPlan,
  parseExportReceipt,
  sameExportGrant,
  type ExportAuditEvent,
  type ExportCapabilities,
  type ExportPlan,
  type ExportReceipt,
  type PendingExport,
  type PendingExports,
} from "@/core/evaluation/export-policy";

const selectClass =
  "bg-background w-full min-w-0 rounded-md border px-3 py-2 text-sm";

/** Key by project/locale. Parent owns page-memory pending IDs and the cross-project write lock. */
export function AuthorizedExportPanel({
  projectId,
  zh,
  pendingExports,
  writeLock,
}: {
  projectId: string;
  zh: boolean;
  pendingExports: PendingExports;
  writeLock: MutableRefObject<boolean>;
}) {
  const t = (en: string, cn: string) => (zh ? cn : en);
  const base = `evaluation/projects/${encodeURIComponent(projectId)}`;
  const [capabilities, setCapabilities] = useState<ExportCapabilities | null>(
    null,
  );
  const [grantId, setGrantId] = useState("");
  const [plan, setPlan] = useState<ExportPlan | null>(null);
  const [pending, setPending] = useState<PendingExport | null>(
    () => pendingExports.get(projectId) ?? null,
  );
  const [opened, setOpened] = useState<ExportReceipt | null>(null);
  const [lookup, setLookup] = useState("");
  const [consent, setConsent] = useState(false);
  const [dataConsent, setDataConsent] = useState(false);
  const [externalConsent, setExternalConsent] = useState(false);
  const [downloadConsent, setDownloadConsent] = useState(false);
  const [events, setEvents] = useState<ExportAuditEvent[] | null>(null);
  const [cursor, setCursor] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const lock = useRef(false),
    epoch = useRef(0);
  useEffect(() => {
    const lifecycle = epoch;
    return () => {
      lifecycle.current++;
    };
  }, []);
  const grant = capabilities?.grants.find((g) => g.id === grantId);
  function revoke() {
    setConsent(false);
    setDataConsent(false);
    setExternalConsent(false);
    setDownloadConsent(false);
  }
  async function operation(fn: (current: () => boolean) => Promise<void>) {
    if (lock.current) return;
    lock.current = true;
    const token = epoch.current,
      current = () => token === epoch.current;
    setBusy(true);
    setError(false);
    revoke();
    try {
      await fn(current);
    } catch {
      if (current()) setError(true);
    } finally {
      lock.current = false;
      if (current()) setBusy(false);
    }
  }
  async function loadCapabilities() {
    setCapabilities(null);
    setGrantId("");
    setPlan(null);
    await operation(async (current) => {
      const result = parseExportCapabilities(
        await evaluationApi<unknown>(base + "/export-capabilities"),
        projectId,
      );
      if (current()) setCapabilities(result);
    });
  }
  async function openPlan() {
    if (!grant) return;
    setPlan(null);
    await operation(async (current) => {
      const result = parseExportPlan(
        await evaluationApi<unknown>(
          base + "/plans/" + encodeURIComponent(grant.plan_id),
        ),
        grant,
      );
      if (current()) setPlan(result);
    });
  }
  function finish(
    raw: unknown,
    remembered: PendingExport,
    current: () => boolean,
  ) {
    const receipt = parseExportReceipt(
      raw,
      projectId,
      remembered.id,
      remembered,
    );
    if (!current() || pendingExports.get(projectId) !== remembered) return;
    pendingExports.delete(projectId);
    setPending(null);
    setOpened(receipt);
    setLookup(receipt.id);
    setEvents(null);
    setCursor(null);
    setPlan(null);
  }
  const ready =
    !!capabilities?.enabled &&
    !!capabilities.software_archive_sha256 &&
    !!grant &&
    grant.expires_at_ms > Date.now() &&
    !!plan &&
    plan.id === grant.plan_id &&
    plan.hash === grant.plan_hash;
  async function create() {
    if (
      lock.current ||
      writeLock.current ||
      pendingExports.has(projectId) ||
      !ready ||
      !grant ||
      !plan ||
      !capabilities?.software_archive_sha256 ||
      !consent ||
      !dataConsent ||
      !externalConsent
    )
      return;
    if (grant.expires_at_ms <= Date.now()) {
      revoke();
      setError(true);
      return;
    }
    const id = crypto.randomUUID().replaceAll("-", "");
    const remembered: PendingExport = {
      id,
      projectId,
      grant: { ...grant },
      sampleCount: plan.sampleCount,
      planSchema: plan.schema,
      softwareHash: capabilities.software_archive_sha256,
      request: {
        plan_id: plan.id,
        plan_hash: plan.hash,
        grant_id: grant.id,
        recipient_id: grant.recipient_id,
        tier: grant.tier,
        confirmed: true,
        data_use_confirmed: true,
        external_controls_acknowledged: true,
      },
    };
    // Preserve the original ID before the first await, including failed/404 reconciliation.
    pendingExports.set(projectId, remembered);
    setPending(remembered);
    setOpened(null);
    setEvents(null);
    setCursor(null);
    writeLock.current = true;
    try {
      await operation(async (current) =>
        finish(
          await evaluationApi<unknown>(
            base + "/exports/" + id,
            remembered.request,
            "PUT",
          ),
          remembered,
          current,
        ),
      );
    } finally {
      writeLock.current = false;
    }
  }
  async function reconcile() {
    const remembered = pendingExports.get(projectId);
    if (!remembered) return;
    await operation(async (current) =>
      finish(
        await evaluationApi<unknown>(base + "/exports/" + remembered.id),
        remembered,
        current,
      ),
    );
  }
  async function openReceipt() {
    if (!exportIdValid(lookup)) return;
    const id = lookup;
    setOpened(null);
    setEvents(null);
    setCursor(null);
    await operation(async (current) => {
      const receipt = parseExportReceipt(
        await evaluationApi<unknown>(base + "/exports/" + id),
        projectId,
        id,
      );
      if (current()) setOpened(receipt);
    });
  }
  const downloadable =
    !!opened &&
    !!capabilities?.enabled &&
    capabilities.software_archive_sha256 === opened.software_archive_sha256 &&
    capabilities.grants.some(
      (g) => sameExportGrant(g, opened.grant) && g.expires_at_ms > Date.now(),
    );
  async function download() {
    if (!opened || !downloadable || !downloadConsent) return;
    const receipt = opened;
    if (receipt.grant.expires_at_ms <= Date.now()) {
      revoke();
      setError(true);
      return;
    }
    await operation(async (current) => {
      const blob = await evaluationExportBundle(receipt);
      if (!current()) return;
      if (receipt.grant.expires_at_ms <= Date.now())
        throw new Error("Export grant expired");
      const url = URL.createObjectURL(blob),
        anchor = document.createElement("a");
      try {
        anchor.href = url;
        anchor.download = `qa-config-${receipt.id}.zip`;
        document.body.appendChild(anchor);
        anchor.click();
      } finally {
        anchor.remove();
        URL.revokeObjectURL(url);
      }
      setEvents(null);
      setCursor(null);
    });
  }
  async function loadAudit(after = 0) {
    if (!opened) return;
    const receipt = opened;
    if (after === 0) {
      setEvents(null);
      setCursor(null);
    }
    await operation(async (current) => {
      const page = parseExportAudit(
        await evaluationApi<unknown>(
          base +
            "/exports/" +
            receipt.id +
            `/audit?after_sequence=${after}&limit=100`,
        ),
        receipt,
        after,
      );
      if (current()) {
        setEvents((old) =>
          after === 0 ? page.events : [...(old ?? []), ...page.events],
        );
        setCursor(page.next_after_sequence);
      }
    });
  }
  return (
    <section
      aria-label={t("Authorized QA configuration exports", "授权 QA 配置导出")}
      className="min-w-0 space-y-4 rounded-xl border p-5"
    >
      <h2 className="font-semibold">
        {t("Authorized QA configuration exports", "授权 QA 配置导出")}
      </h2>
      <p className="text-muted-foreground text-sm leading-6">
        {t(
          "Configuration only — NOT_EVALUATED. No execution or approval. Skeletons lack inputs; baseline exports include ALL frozen inputs only, never reference answers, historical outputs or request values. Rebind ALL request values and obtain separate execution authorization. Software must be obtained separately through a trusted channel.",
          "仅配置，NOT_EVALUATED，不是执行授权或批准。骨架缺少输入；baseline 仅含全部冻结输入，不含金标、历史输出或请求值。必须重新绑定全部请求值并另行取得执行授权；软件发行包须通过独立可信渠道取得。",
        )}
      </p>
      <Button
        variant="outline"
        disabled={busy}
        onClick={() => void loadCapabilities()}
      >
        {t("Load export policy and grants", "加载导出策略与授权")}
      </Button>
      {capabilities && (
        <div className="space-y-2 text-sm">
          <p>
            {capabilities.enabled
              ? t(
                  "Operator policy enabled; not a source/permission guarantee.",
                  "操作员策略已启用，不保证来源可导出或当前权限有效。",
                )
              : t(
                  "Export is disabled by the operator. Historical receipts remain readable.",
                  "操作员未启用导出，历史回执仍可读取。",
                )}
          </p>
          {capabilities.software_archive_sha256 && (
            <p className="break-all">
              {t("Separate software SHA-256: ", "独立软件 SHA-256：")}
              {capabilities.software_archive_sha256}
            </p>
          )}
          <p>
            {t(
              "Response byte limits (per attempt / total): ",
              "响应字节限额（单次 / 总计）：",
            )}
            {capabilities.max_response_bytes} /{" "}
            {capabilities.max_total_response_bytes}
          </p>
          <label className="block space-y-1">
            {t("Exact export grant", "精确导出授权")}
            <select
              aria-label={t("Exact export grant", "精确导出授权")}
              className={selectClass}
              value={grantId}
              disabled={busy || !!pending}
              onChange={(e) => {
                setGrantId(e.target.value);
                setPlan(null);
                revoke();
              }}
            >
              <option value="">
                {t("Select an explicit grant", "显式选择授权")}
              </option>
              {capabilities.grants.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.plan_id} — {g.tier} — {g.recipient_id}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}
      {grant && (
        <div className="space-y-2 text-sm">
          <p className="break-all">
            {t("Recipient account: ", "接收方账户：")}
            {grant.recipient_id}
          </p>
          <p className="break-all">
            {t("Authorized origin: ", "授权目标源：")}
            {grant.target_origin}
          </p>
          <p className="break-all">
            {t("Frozen plan hash: ", "冻结计划哈希：")}
            {grant.plan_hash}
          </p>
          <p>
            {t("Grant expiry: ", "授权到期：")}
            {new Date(grant.expires_at_ms).toISOString()}
          </p>
          <Button
            variant="outline"
            disabled={busy || !!pending}
            onClick={() => void openPlan()}
          >
            {t("Open selected frozen plan", "打开选定冻结计划")}
          </Button>
        </div>
      )}
      {plan && (
        <p className="text-sm">
          {plan.label} · {plan.schema} ·{" "}
          {t("ALL frozen samples: ", "全部冻结样本：")}
          {plan.sampleCount}
        </p>
      )}
      <div className="space-y-2 text-sm">
        <label className="flex items-start gap-2">
          <input
            type="checkbox"
            checked={consent}
            disabled={busy || !!pending || !ready}
            onChange={(e) => setConsent(e.target.checked)}
          />
          {t(
            "I confirm this exact source, grant, recipient and tier.",
            "我确认此精确来源、授权、接收方和数据级别。",
          )}
        </label>
        <label className="flex items-start gap-2">
          <input
            type="checkbox"
            checked={dataConsent}
            disabled={busy || !!pending || !ready}
            onChange={(e) => setDataConsent(e.target.checked)}
          />
          {t(
            "I separately authorize the selected data to leave the platform.",
            "我单独授权所选数据离开平台。",
          )}
        </label>
        <label className="flex items-start gap-2">
          <input
            type="checkbox"
            checked={externalConsent}
            disabled={busy || !!pending || !ready}
            onChange={(e) => setExternalConsent(e.target.checked)}
          />
          {t(
            "I acknowledge external destination, load, output protection and retention controls remain separate responsibilities.",
            "我知悉外部目标、负载、输出保护与保留控制仍须单独落实。",
          )}
        </label>
      </div>
      <Button
        disabled={
          busy ||
          !!pending ||
          writeLock.current ||
          !ready ||
          !consent ||
          !dataConsent ||
          !externalConsent
        }
        onClick={() => void create()}
      >
        {t("Create authorized configuration archive", "创建授权配置档案")}
      </Button>
      {pending && (
        <div role="status" className="space-y-2 rounded-md border p-3 text-sm">
          <p>
            {t(
              "Write outcome unresolved. Only GET this same ID, including after a 404; never resend PUT or replace the ID automatically. Record this ID before leaving the page.",
              "写入结果尚未核实。包括 GET 404 后也只能查询同一 ID，不重发 PUT、不自动换 ID。离开页面前请记录此 ID。",
            )}
          </p>
          <code className="block break-all">{pending.id}</code>
          <Button
            variant="outline"
            disabled={busy}
            onClick={() => void reconcile()}
          >
            {t("Reconcile the same export ID", "核对同一导出 ID")}
          </Button>
        </div>
      )}
      <div className="space-y-2 border-t pt-4">
        <label className="block space-y-1">
          {t("Historical export ID", "历史导出 ID")}
          <Input
            value={lookup}
            disabled={busy}
            maxLength={32}
            onChange={(e) => {
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
          disabled={busy || !exportIdValid(lookup)}
          onClick={() => void openReceipt()}
        >
          {t("Open exact export receipt", "打开精确导出回执")}
        </Button>
      </div>
      {opened && (
        <div className="space-y-3 rounded-md border p-3 text-sm">
          <p>
            {t(
              "Historical configuration receipt — NOT_EVALUATED",
              "历史配置回执 — NOT_EVALUATED",
            )}
          </p>
          <dl className="grid min-w-0 gap-2 sm:grid-cols-2">
            {[
              [t("Export ID", "导出 ID"), opened.id],
              [t("Plan ID", "计划 ID"), opened.plan_id],
              [t("Recipient", "接收方"), opened.recipient_id],
              [t("Tier", "数据级别"), opened.tier],
              [
                t("ALL frozen samples", "全部冻结样本"),
                opened.all_frozen_samples,
              ],
              [t("Receipt hash", "回执哈希"), opened.receipt_hash],
              [
                t("Software SHA-256", "软件 SHA-256"),
                opened.software_archive_sha256,
              ],
            ].map(([label, value]) => (
              <div key={label} className="min-w-0">
                <dt className="text-muted-foreground">{label}</dt>
                <dd className="break-all">{value}</dd>
              </div>
            ))}
          </dl>
          <p>
            {opened.input_set_complete
              ? t(
                  "ALL baseline inputs included; request values still unbound.",
                  "已包含全部 baseline 输入，请求值仍未绑定。",
                )
              : t(
                  "Skeleton inputs are incomplete; evaluation cannot yet be completed.",
                  "骨架输入不完整，目前不能完成评测。",
                )}
          </p>
          <label className="flex items-start gap-2">
            <input
              type="checkbox"
              checked={downloadConsent}
              disabled={busy || !downloadable}
              onChange={(e) => setDownloadConsent(e.target.checked)}
            />
            {t(
              "I confirm downloading this viewed configuration to my device for the declared recipient.",
              "我确认将此已查看配置下载到本机，并仅交付给声明的接收方。",
            )}
          </label>
          <Button
            disabled={busy || !downloadable || !downloadConsent}
            onClick={() => void download()}
          >
            {t("Download viewed configuration ZIP", "下载已查看配置 ZIP")}
          </Button>
          {!downloadable && (
            <p>
              {t(
                "Download requires a freshly loaded matching enabled policy, exact unexpired grant and software pin; the server rechecks them.",
                "下载需要手动加载匹配且已启用的策略、未过期精确授权与软件哈希，服务端会再次核对。",
              )}
            </p>
          )}
          <div>
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => void loadAudit()}
            >
              {t("Load export audit", "加载导出审计")}
            </Button>
          </div>
          {events && (
            <ol className="space-y-1">
              {events.map((e) => (
                <li key={e.id}>
                  {e.sequence} · {e.action} · {e.at_ms}
                </li>
              ))}
            </ol>
          )}
          {cursor !== null && (
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => void loadAudit(cursor)}
            >
              {t("Load next audit page", "加载下一页审计")}
            </Button>
          )}
        </div>
      )}
      {error && (
        <p role="alert" className="text-sm">
          {t(
            "Operation not confirmed. Check permissions, exact sources, policy, expiry and configuration. No automatic retry or resend; unresolved writes retain their original ID.",
            "操作未确认。请核对权限、精确来源、策略、有效期与配置。不会自动重试或重发；未决写入保留原 ID。",
          )}
        </p>
      )}
    </section>
  );
}

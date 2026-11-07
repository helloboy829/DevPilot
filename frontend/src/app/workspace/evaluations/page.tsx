"use client";

import {
  ArrowRight,
  Database,
  CalendarClock,
  CheckCircle2,
  FileText,
  FlaskConical,
  Layers3,
  Settings2,
} from "lucide-react";
import Link from "next/link";

import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useComponents } from "@/core/component-tests/hooks";
import { useI18n } from "@/core/i18n/hooks";

export default function EvaluationHome() {
  const { locale } = useI18n();
  const zh = locale === "zh-CN";
  const inventory = useComponents();
  const components = inventory.data ?? [];
  const steps = [
    {
      icon: FlaskConical,
      title: zh ? "01 接口接入" : "01 Connect targets",
      description: zh
        ? "粘贴 cURL、解析并编辑请求，授权后验证响应。"
        : "Import cURL, inspect and edit the request, then authorize a connectivity check.",
      href: "/workspace/component-tests",
      action: zh ? "从 cURL 开始" : "Start with cURL",
    },
    {
      icon: Database,
      title: zh ? "02 项目与数据" : "02 Projects & datasets",
      description: zh
        ? "登记来源、导入 QA、检查预期答案后冻结数据版本。"
        : "Declare sources, import QA, review reference answers and freeze dataset versions.",
      href: "/workspace/datasets",
      action: zh ? "管理评测数据" : "Manage evaluation data",
    },
    {
      icon: CalendarClock,
      title: zh ? "03 执行评测" : "03 Run evaluations",
      description: zh
        ? "区分效果与性能，使用受限参数或安排低峰时段。"
        : "Separate effect and performance testing, with bounded load and off-peak schedules.",
      href: "/workspace/evaluation-schedules",
      action: zh ? "安排评测时段" : "Schedule evaluations",
    },
    {
      icon: FileText,
      title: zh ? "04 汇总报告" : "04 Assemble reports",
      description: zh
        ? "与助手逐轮明确需求，确认多组件事实，再生成版本固定的草稿。"
        : "Clarify requirements over multiple turns, confirm component facts, then render a version-pinned draft.",
      href: "/workspace/reports",
      action: zh ? "进入报告工作区" : "Open report workspace",
    },
  ];
  return (
    <WorkspaceContainer>
      <WorkspaceHeader>
        <h1 className="text-lg font-semibold">
          {zh ? "评测工作台" : "Evaluation workbench"}
        </h1>
      </WorkspaceHeader>
      <WorkspaceBody className="overflow-y-auto">
        <div className="mx-auto w-full max-w-7xl space-y-7 p-4 md:p-8">
          <section className="via-background relative overflow-hidden rounded-2xl border bg-gradient-to-br from-sky-500/10 to-emerald-500/10 p-6 md:p-8">
            <p className="text-muted-foreground mb-3 text-xs font-semibold tracking-widest">
              DEVPILOT / AI EVALUATION
            </p>
            <h2 className="max-w-3xl text-2xl font-semibold tracking-tight md:text-3xl">
              {zh
                ? "围绕评测证据，而不只是对话。"
                : "Built around evaluation evidence, not just conversation."}
            </h2>
            <p className="text-muted-foreground mt-3 max-w-3xl text-sm leading-6">
              {zh
                ? "从接口验证，到效果、性能与多组件报告。Agent 辅助整理和解释，执行授权、实测指标与最终验收由确定性服务和人负责。"
                : "From API verification to effect, performance and multi-component reporting. Agents assist; authorized execution, measured facts and acceptance stay under deterministic and human control."}
            </p>
            <div className="mt-5 flex flex-wrap gap-3">
              <Link
                className="bg-primary text-primary-foreground inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium"
                href="/workspace/component-tests"
              >
                {zh ? "开始组件评测" : "New component evaluation"}
                <ArrowRight className="size-4" />
              </Link>
              <Link
                className="bg-background inline-flex items-center gap-2 rounded-lg border px-4 py-2 text-sm"
                href="/workspace/models"
              >
                <Settings2 className="size-4" />
                {zh ? "配置工作模型" : "Configure working models"}
              </Link>
            </div>
          </section>
          <section
            className="grid gap-4 md:grid-cols-2 xl:grid-cols-4"
            aria-label={zh ? "评测流程" : "Evaluation workflow"}
          >
            {steps.map((step) => (
              <article
                key={step.href}
                className="bg-card flex flex-col rounded-xl border p-5"
              >
                <step.icon className="text-primary mb-4 size-6" />
                <h2 className="font-semibold">{step.title}</h2>
                <p className="text-muted-foreground mt-2 flex-1 text-sm leading-6">
                  {step.description}
                </p>
                <Link
                  href={step.href}
                  className="mt-5 inline-flex items-center gap-2 text-sm font-medium"
                >
                  {step.action}
                  <ArrowRight className="size-4" />
                </Link>
              </article>
            ))}
          </section>
          <div className="grid gap-6 lg:grid-cols-[1.5fr_1fr]">
            <section className="bg-card rounded-xl border p-5">
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                <h2 className="flex items-center gap-2 font-semibold">
                  <Layers3 className="size-5" />
                  {zh ? "我的被测组件" : "My target components"}
                </h2>
                <button
                  className="text-sm underline underline-offset-4"
                  disabled={inventory.isFetching}
                  onClick={() => void inventory.refetch()}
                >
                  {zh ? "刷新" : "Refresh"}
                </button>
              </div>
              {inventory.isPending ? (
                <p role="status">
                  {zh ? "正在读取组件…" : "Loading components…"}
                </p>
              ) : inventory.isError ? (
                <p role="alert">
                  {zh
                    ? "组件读取失败；未知不等于零。请重试或检查访问权限。"
                    : "Cannot load inventory. Unknown is not zero; retry or check access."}
                </p>
              ) : (
                <>
                  <p className="text-muted-foreground mb-4 text-sm">
                    {zh ? "已登记" : "Registered"}{" "}
                    <strong className="text-foreground">
                      {components.length}
                    </strong>{" "}
                    · {zh ? "启用" : "Enabled"}{" "}
                    {components.filter((c) => c.enabled).length} ·{" "}
                    {zh ? "这不是验收通过数" : "Not acceptance counts"}
                  </p>
                  {components.length === 0 ? (
                    <div className="rounded-lg border border-dashed p-6 text-sm">
                      {zh
                        ? "还没有组件。先调通请求，再登记被测对象。"
                        : "No targets yet. Verify a request, then register a component."}
                    </div>
                  ) : (
                    <ul className="divide-y">
                      {components.map((c) => (
                        <li key={c.id}>
                          <Link
                            href="/workspace/component-tests"
                            className="flex items-center justify-between gap-3 py-3"
                          >
                            <div>
                              <p className="font-medium">{c.name}</p>
                              <p className="text-muted-foreground text-xs">
                                {c.transport} · {c.response_mode}
                              </p>
                            </div>
                            <span className="text-muted-foreground text-xs">
                              {c.enabled
                                ? zh
                                  ? "已启用"
                                  : "Enabled"
                                : zh
                                  ? "已停用"
                                  : "Disabled"}
                            </span>
                          </Link>
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              )}
            </section>
            <aside className="space-y-4 rounded-xl border p-5">
              <h2 className="font-semibold">
                {zh ? "能力边界与下一步" : "Capability boundaries & next steps"}
              </h2>
              <p className="text-muted-foreground text-sm leading-6">
                {zh
                  ? "当前为可验证的工作台切片，不是已经完成的全自动验收平台。"
                  : "These are verifiable workspace slices, not a complete automated acceptance platform."}
              </p>
              {[
                zh
                  ? "双人独立数据审核、质量卡与执行关联"
                  : "Independent data review, quality cards and execution links",
                zh
                  ? "逐条复核、分配与仲裁中心"
                  : "Case review, assignment and arbitration",
                zh
                  ? "正式报告审批与 DOCX / PDF"
                  : "Formal report approval and DOCX / PDF",
              ].map((text) => (
                <div key={text} className="bg-muted/50 rounded-lg p-3">
                  <p className="text-sm">{text}</p>
                  <span className="text-muted-foreground mt-1 block text-xs">
                    {zh ? "尚未实现" : "Not yet implemented"}
                  </span>
                </div>
              ))}
              <p className="flex gap-2 text-xs leading-5">
                <CheckCircle2 className="mt-0.5 size-4 shrink-0" />
                {zh
                  ? "TTFT 只适用于可观测首内容增量的流式调用；缺测不填零。"
                  : "TTFT requires observable streamed content. Missing measurements are never zero."}
              </p>
            </aside>
          </div>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

"use client";

import { ExecutionOperationsPanel } from "@/components/workspace/execution-operations-panel";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";

export default function OperationsPage() {
  const { locale } = useI18n();
  const zh = locale === "zh-CN";
  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className="overflow-auto">
        <div className="mx-auto w-full max-w-4xl space-y-5 p-4 sm:p-6">
          <h1 className="text-2xl font-semibold">
            {zh ? "执行预留诊断" : "Execution reservation diagnostics"}
          </h1>
          <ExecutionOperationsPanel zh={zh} />
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

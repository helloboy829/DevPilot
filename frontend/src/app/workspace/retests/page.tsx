"use client";

import { EvaluationRetestPanel } from "@/components/workspace/evaluation-retest-panel";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";

export default function RetestsPage() {
  const { locale } = useI18n();
  const zh = locale === "zh-CN";
  return (
    <WorkspaceContainer>
      <WorkspaceHeader>
        <h1 className="text-lg font-semibold">
          {zh ? "整改复测" : "Remediation & retesting"}
        </h1>
      </WorkspaceHeader>
      <WorkspaceBody>
        <main className="mx-auto w-full max-w-6xl p-4 md:p-6">
          <EvaluationRetestPanel zh={zh} />
        </main>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

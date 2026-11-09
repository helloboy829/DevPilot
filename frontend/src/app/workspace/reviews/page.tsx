"use client";

import { ReviewTaskCenter } from "@/components/workspace/review-task-center";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";

export default function ReviewsPage() {
  const { locale } = useI18n();
  const zh = locale === "zh-CN";
  return (
    <WorkspaceContainer>
      <WorkspaceHeader>
        <h1 className="text-lg font-semibold">
          {zh ? "独立复核中心" : "Independent review center"}
        </h1>
      </WorkspaceHeader>
      <WorkspaceBody>
        <main className="mx-auto w-full max-w-6xl min-w-0 p-4 md:p-6">
          <ReviewTaskCenter zh={zh} />
        </main>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

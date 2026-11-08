import type { ReviewSummary } from "./review-types";

export interface ArchiveTemplate {
  id: string;
  version: string;
  language: "zh" | "en";
  layout: Record<string, string>;
}
export interface ArchiveMetadata {
  id: string;
  project_id: string;
  root_id: string;
  revision: number;
  supersedes_id: string | null;
  title: string;
  template_id: string;
  template_version: string;
  created_at_ms: number;
}
export interface ReportArchive extends Omit<
  ArchiveMetadata,
  "template_id" | "template_version"
> {
  schema: "qa-project-report-archive.v1";
  scope: "immutable_qa_report_draft";
  project_name: string;
  template: ArchiveTemplate;
  template_hash: string;
  components: ReviewSummary[];
  markdown: string;
  acceptance: "not_approved";
  archive_hash: string;
}
export interface ArchiveRequest {
  title: string;
  template_id: string;
  template_version: string;
  sources: { run_id: string; summary_hash: string }[];
  supersedes_id: string | null;
  confirmed: true;
}
export interface PendingArchive {
  id: string;
  request: ArchiveRequest;
}

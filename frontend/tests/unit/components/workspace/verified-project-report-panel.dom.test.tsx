import { afterEach, beforeEach, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";

import { VerifiedProjectReportPanel } from "@/components/workspace/verified-project-report-panel";

const state = rs.hoisted(() => ({ api: rs.fn(), docx: rs.fn() }));
rs.mock("@/core/evaluation/api", () => ({
  evaluationApi: state.api,
  evaluationReportDocx: state.docx,
}));
const summary = {
  schema: "qa-human-summary.v1",
  scope: "verified_human_summary_preview",
  run_id: "a".repeat(32),
  project_id: "p1",
  component_id: "c1",
  component_name: "Synthetic first",
  run_status: "recording_finished",
  plan_id: "plan1",
  plan_label: "Plan first",
  plan_hash: "c".repeat(64),
  summary_hash: "d".repeat(64),
  counts: { pass: 1, fail: 1, uncertain: 0, unreviewed: 0 },
  technical_counts: { collected: 2, other: 0 },
  human_pass_rate: { numerator: 1, denominator: 2, value: 0.5 },
  readiness: "review_complete",
  blockers: [],
  acceptance: "not_approved",
};
const template = {
  id: "verified-qa-project-en",
  version: "1.0.0",
  language: "en",
  layout: {},
};
const saved = {
  schema: "qa-project-report-archive.v1",
  scope: "immutable_qa_report_draft",
  id: "e".repeat(32),
  project_id: "p1",
  project_name: "Synthetic project",
  root_id: "e".repeat(32),
  revision: 1,
  supersedes_id: null,
  title: "Synthetic report",
  created_at_ms: 1800000000000,
  template,
  template_hash: "f".repeat(64),
  components: [summary],
  markdown: "# Synthetic immutable DRAFT",
  acceptance: "not_approved",
  archive_hash: "b".repeat(64),
};
function respond(route: string, body?: unknown, method?: string): unknown {
  if (route === "evaluation/projects")
    return {
      projects: [
        { id: "p1", name: "Synthetic project" },
        { id: "p2", name: "Other project" },
      ],
    };
  if (route.endsWith("/report-templates")) return { templates: [template] };
  if (route.endsWith("/review-runs"))
    return { runs: [{ ...summary, id: summary.run_id }] };
  if (route.endsWith("/summary")) return summary;
  if (route.endsWith("/report-archives")) return { archives: [] };
  if (method === "PUT")
    return {
      ...saved,
      id: route.split("/").at(-1),
      root_id: route.split("/").at(-1),
      ...((body as { supersedes_id?: string }).supersedes_id
        ? { supersedes_id: saved.id, revision: 2, root_id: saved.id }
        : {}),
    };
  return saved;
}
beforeEach(() => {
  state.api.mockReset();
  state.docx.mockReset();
  state.api.mockImplementation(async (...args: [string, unknown?, string?]) =>
    respond(...args),
  );
});
afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
});
async function loaded() {
  render(<VerifiedProjectReportPanel zh={false} />);
  expect(state.api).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Load projects" }));
  await screen.findByRole("option", { name: "Synthetic project" });
  fireEvent.change(screen.getByRole("combobox", { name: "Report project" }), {
    target: { value: "p1" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Load runs, templates and archives" }),
  );
  await screen.findByRole("option", { name: /Synthetic first/ });
  expect(
    screen.getByRole("combobox", { name: "Archive template" }),
  ).toBeTruthy();
}
async function staged() {
  await loaded();
  fireEvent.change(screen.getByRole("combobox", { name: "Evidence run" }), {
    target: { value: summary.run_id },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Verify selected summary" }),
  );
  await screen.findByRole("button", { name: "Add verified component" });
  fireEvent.click(
    screen.getByRole("button", { name: "Add verified component" }),
  );
  fireEvent.change(screen.getByLabelText("Archive title"), {
    target: { value: "  Synthetic report  " },
  });
}
it("requires explicit load/consent; sends references, not metrics; locks double writes", async () => {
  await staged();
  const save = screen.getByRole<HTMLButtonElement>("button", {
    name: "Archive verified draft",
  });
  expect(save.disabled).toBe(true);
  fireEvent.click(screen.getByLabelText("Confirm immutable draft storage"));
  fireEvent.click(save);
  fireEvent.click(save);
  await screen.findByText("# Synthetic immutable DRAFT");
  const puts = state.api.mock.calls.filter((call) => call[2] === "PUT");
  expect(puts).toHaveLength(1);
  expect(puts[0]?.[0]).toMatch(/report-archives\/[a-f0-9]{32}$/);
  expect(puts[0]?.[1]).toEqual({
    title: "Synthetic report",
    template_id: template.id,
    template_version: template.version,
    sources: [{ run_id: summary.run_id, summary_hash: summary.summary_hash }],
    supersedes_id: null,
    confirmed: true,
  });
  fireEvent.change(screen.getByLabelText("Archive title"), {
    target: { value: "Edited" },
  });
  expect(
    screen.getByLabelText<HTMLInputElement>("Confirm immutable draft storage")
      .checked,
  ).toBe(false);
  expect(screen.getByText("# Synthetic immutable DRAFT")).toBeTruthy();
});
it("blocks incomplete summaries", async () => {
  await loaded();
  state.api.mockImplementation(async (route: string) =>
    route.endsWith("/summary")
      ? { ...summary, readiness: "provisional", blockers: ["uncertain"] }
      : respond(route),
  );
  fireEvent.change(screen.getByRole("combobox", { name: "Evidence run" }), {
    target: { value: summary.run_id },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Verify selected summary" }),
  );
  await screen.findByText(/Review incomplete/);
  expect(
    screen.getByRole<HTMLButtonElement>("button", {
      name: "Add verified component",
    }).disabled,
  ).toBe(true);
});
it("reconciles unknown PUT by same-ID GET only, without leaking errors", async () => {
  await staged();
  state.api.mockImplementation(
    async (route: string, body?: unknown, method?: string) => {
      if (method === "PUT") throw new Error("SYNTHETIC_PRIVATE_ERROR");
      return respond(route, body, method);
    },
  );
  fireEvent.click(screen.getByLabelText("Confirm immutable draft storage"));
  fireEvent.click(
    screen.getByRole("button", { name: "Archive verified draft" }),
  );
  await screen.findByRole("button", { name: "Check pending archive receipt" });
  expect(screen.queryByText(/SYNTHETIC_PRIVATE_ERROR/)).toBeNull();
  expect(
    screen.getByLabelText("Archive title").closest("fieldset")!.disabled,
  ).toBe(true);
  const put = state.api.mock.calls.find((call) => call[2] === "PUT")!;
  state.api.mockImplementation(async (route: string) => ({
    ...saved,
    id: route.split("/").at(-1),
    root_id: route.split("/").at(-1),
  }));
  fireEvent.click(
    screen.getByRole("button", { name: "Check pending archive receipt" }),
  );
  await screen.findByText("# Synthetic immutable DRAFT");
  expect(state.api.mock.calls.filter((call) => call[2] === "PUT")).toHaveLength(
    1,
  );
  expect(state.api.mock.calls.at(-1)).toEqual([put[0]]);
});
it("ignores a late receipt after project change", async () => {
  await staged();
  let resolve!: (value: unknown) => void;
  state.api.mockImplementation(
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  );
  fireEvent.click(screen.getByLabelText("Confirm immutable draft storage"));
  fireEvent.click(
    screen.getByRole("button", { name: "Archive verified draft" }),
  );
  fireEvent.change(screen.getByRole("combobox", { name: "Report project" }), {
    target: { value: "p2" },
  });
  await act(async () => resolve(saved));
  expect(screen.queryByText("# Synthetic immutable DRAFT")).toBeNull();
});
it("opens frozen history and writes a new revision, never the old ID", async () => {
  state.api.mockImplementation(
    async (route: string, body?: unknown, method?: string) =>
      route.endsWith("/report-archives")
        ? { archives: [saved] }
        : respond(route, body, method),
  );
  await staged();
  fireEvent.click(
    screen.getByRole("button", { name: /Open.*Synthetic report/ }),
  );
  await screen.findByText("# Synthetic immutable DRAFT");
  fireEvent.click(
    screen.getByRole("button", { name: "Use as revision parent" }),
  );
  expect(screen.getByText(/New revision of/)).toBeTruthy();
  fireEvent.click(screen.getByLabelText("Confirm immutable draft storage"));
  fireEvent.click(
    screen.getByRole("button", { name: "Archive verified draft" }),
  );
  await screen.findByText(/Revision 2/);
  const call = state.api.mock.calls.find((call) => call[2] === "PUT")!;
  expect(call[0]).not.toContain(saved.id);
  expect((call[1] as { supersedes_id: string }).supersedes_id).toBe(saved.id);
});

it("keeps an unknown receipt pending across project switches and failed checks", async () => {
  await staged();
  state.api.mockImplementation(async () => {
    throw new Error("Synthetic unavailable");
  });
  fireEvent.click(screen.getByLabelText("Confirm immutable draft storage"));
  fireEvent.click(
    screen.getByRole("button", { name: "Archive verified draft" }),
  );
  await screen.findByRole("alert");
  const put = state.api.mock.calls.find((call) => call[2] === "PUT")!;
  fireEvent.change(screen.getByRole("combobox", { name: "Report project" }), {
    target: { value: "p2" },
  });
  fireEvent.change(screen.getByRole("combobox", { name: "Report project" }), {
    target: { value: "p1" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Check pending archive receipt" }),
  );
  await screen.findByRole("alert");
  expect(state.api.mock.calls.at(-1)).toEqual([put[0]]);
  expect(state.api.mock.calls.filter((call) => call[2] === "PUT")).toHaveLength(
    1,
  );
  expect(
    screen.getByLabelText("Archive title").closest("fieldset")!.disabled,
  ).toBe(true);
  state.api.mockResolvedValue(saved); // Different ID must not unlock the pending write.
  fireEvent.click(
    screen.getByRole("button", { name: "Check pending archive receipt" }),
  );
  await screen.findByRole("alert");
  expect(screen.queryByText("# Synthetic immutable DRAFT")).toBeNull();
});
it("does not allow a second run for an already staged component", async () => {
  await staged();
  fireEvent.click(
    screen.getByRole("button", { name: "Verify selected summary" }),
  );
  const add = await screen.findByRole<HTMLButtonElement>("button", {
    name: "Add verified component",
  });
  expect(add.disabled).toBe(true);
});

it("gives Chinese selectors stable names independent of their options", async () => {
  render(<VerifiedProjectReportPanel zh />);
  fireEvent.click(screen.getByRole("button", { name: "加载项目" }));
  await screen.findByRole("option", { name: "Synthetic project" });
  fireEvent.change(screen.getByRole("combobox", { name: "报告项目" }), {
    target: { value: "p1" },
  });
  fireEvent.click(
    screen.getByRole("button", {
      name: "加载运行、模板和历史存档",
    }),
  );
  await screen.findByRole("option", { name: /Synthetic first/ });
  expect(screen.getByRole("combobox", { name: "证据运行" })).toBeTruthy();
  expect(screen.getByRole("combobox", { name: "存档模板" })).toBeTruthy();
});

async function archived() {
  await staged();
  fireEvent.click(screen.getByLabelText("Confirm immutable draft storage"));
  fireEvent.click(
    screen.getByRole("button", { name: "Archive verified draft" }),
  );
  await screen.findByText("# Synthetic immutable DRAFT");
}
it("downloads Word only on click, uses the viewed receipt, and fences duplicate clicks", async () => {
  await archived();
  expect(state.docx).not.toHaveBeenCalled();
  const anchor = rs
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => undefined);
  const blob = new Blob(["synthetic ZIP"]);
  const create = rs
    .spyOn(URL, "createObjectURL")
    .mockReturnValue("blob:synthetic");
  const revoke = rs
    .spyOn(URL, "revokeObjectURL")
    .mockImplementation(() => undefined);
  state.docx.mockResolvedValue(blob);
  const button = screen.getByRole("button", { name: "Download Word draft" });
  fireEvent.click(button);
  fireEvent.click(button);
  await act(async () => {
    await Promise.resolve();
  });
  const put = state.api.mock.calls.find((call) => call[2] === "PUT")!;
  expect(state.docx.mock.calls).toEqual([
    [`${put[0]}/exports/qa-docx-v1?archive_hash=${saved.archive_hash}`],
  ]);
  expect(create).toHaveBeenCalledWith(blob);
  expect(anchor).toHaveBeenCalledOnce();
  expect(revoke).toHaveBeenCalledWith("blob:synthetic");
});
it("does not save a late Word response after switching projects", async () => {
  await archived();
  let resolve!: (blob: Blob) => void;
  state.docx.mockImplementation(
    () =>
      new Promise<Blob>((done) => {
        resolve = done;
      }),
  );
  const create = rs.spyOn(URL, "createObjectURL");
  fireEvent.click(screen.getByRole("button", { name: "Download Word draft" }));
  fireEvent.change(screen.getByRole("combobox", { name: "Report project" }), {
    target: { value: "p2" },
  });
  await act(async () => {
    resolve(new Blob(["late"]));
  });
  expect(create).not.toHaveBeenCalled();
  expect(screen.queryByText("# Synthetic immutable DRAFT")).toBeNull();
});
it("shows export failure without saving a fake document or retrying", async () => {
  await archived();
  state.docx.mockRejectedValue(new Error("Synthetic failed export"));
  const create = rs.spyOn(URL, "createObjectURL");
  fireEvent.click(screen.getByRole("button", { name: "Download Word draft" }));
  await screen.findByRole("alert");
  expect(state.docx).toHaveBeenCalledOnce();
  expect(create).not.toHaveBeenCalled();
  expect(screen.getByText("# Synthetic immutable DRAFT")).toBeTruthy();
});

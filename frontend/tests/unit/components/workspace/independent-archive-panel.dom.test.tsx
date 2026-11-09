import { afterEach, beforeEach, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";

import { IndependentArchiveWorkspace } from "@/components/workspace/independent-archive-panel";
import {
  independentPendingKey,
  type PendingIndependentArchives,
} from "@/core/evaluation/independent-archive-policy";

import {
  assessmentArchive,
  assessmentId,
  assessmentMetadata,
  provisionalAssessment,
} from "../../../fixtures/assessment";
import {
  independentReport,
  independentRetest,
  independentTemplate,
} from "../../../fixtures/independent-archive";
const state = rs.hoisted(() => ({
  api: rs.fn(),
  word: rs.fn(),
  retestWord: rs.fn(),
}));
rs.mock("@/core/evaluation/api", () => ({
  evaluationApi: state.api,
  evaluationIndependentReportDocx: state.word,
  evaluationIndependentRetestDocx: state.retestWord,
}));
const writes = () => state.api.mock.calls.filter((c: unknown[]) => c[1]);
function response(route: string, body?: unknown) {
  if (route.endsWith("/review-runs"))
    return {
      runs: [
        { id: "r1", component_name: "Synthetic", plan_label: "v1" },
        { id: "r2", component_name: "Synthetic", plan_label: "v2" },
      ],
    };
  if (route.endsWith("/independent-report-templates"))
    return { templates: [independentTemplate] };
  if (/independent-(report|retest)-archives$/.test(route)) return [];
  const run = route.includes("/r2/") ? "r2" : "r1";
  if (route.endsWith("/assessments"))
    return [
      assessmentMetadata(
        assessmentArchive({
          run_id: run,
          id: run === "r1" ? assessmentId : "d".repeat(32),
        }),
      ),
    ];
  if (route.includes("/assessments/")) {
    const original = assessmentArchive({
      id: run === "r1" ? assessmentId : "d".repeat(32),
    });
    return {
      ...original,
      run_id: run,
      assessment: {
        ...original.assessment,
        run_id: run,
        plan_id: run + "plan",
        plan_label: run + " frozen version",
      },
    };
  }
  const id = route.split("/").at(-1)!;
  return route.includes("retest-archives")
    ? independentRetest(id)
    : {
        ...independentReport(id),
        title: (body as { title?: string })?.title ?? "Independent draft",
      };
}
beforeEach(() => {
  state.api.mockReset();
  state.word.mockReset();
  state.retestWord.mockReset();
  state.api.mockImplementation(response);
});
afterEach(cleanup);
const click = async (name: string) => {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name }));
  });
};
function mount(
  kind: "report" | "retest" = "report",
  pending: PendingIndependentArchives = new Map(),
  projectId = "p1",
) {
  const writeLock = { current: false };
  const props = {
    kind,
    projectId,
    zh: false,
    pendingArchives: pending,
    writeLock,
  };
  return {
    pending,
    writeLock,
    ...render(<IndependentArchiveWorkspace key={projectId} {...props} />),
  };
}
async function load() {
  await click("Load independent runs, templates and archives");
}
async function source(run = "r1") {
  fireEvent.change(screen.getByLabelText("Historical assessment run"), {
    target: { value: run },
  });
  await click("Load historical independent assessment revisions");
  expect(
    screen.getByLabelText<HTMLSelectElement>("Explicit historical revision")
      .value,
  ).toBe("");
  fireEvent.change(screen.getByLabelText("Explicit historical revision"), {
    target: { value: run === "r1" ? assessmentId : "d".repeat(32) },
  });
  await click("Open selected historical assessment");
}
async function prepare() {
  await load();
  await source();
  await click("Add independent report component");
  fireEvent.change(screen.getByLabelText("Independent report title"), {
    target: { value: "Independent draft" },
  });
  fireEvent.change(screen.getByLabelText("Independent pinned template"), {
    target: { value: independentTemplate.id },
  });
}
const confirm = () => fireEvent.click(screen.getByRole("checkbox"));
it("requires explicit historical opens and consent, pins exact sources, and never reads live review, gold or output", async () => {
  mount();
  expect(state.api).not.toHaveBeenCalled();
  await prepare();
  expect(
    screen.getAllByText("1 / 2 · 50.00% · review_complete · not_approved")
      .length,
  ).toBeGreaterThan(0);
  expect(
    screen.getByRole<HTMLButtonElement>("button", {
      name: "Create independent report draft",
    }).disabled,
  ).toBe(true);
  confirm();
  await click("Create independent report draft");
  expect(writes()).toHaveLength(1);
  expect(writes()[0]![2]).toBe("PUT");
  expect(writes()[0]![1]).toEqual({
    title: "Independent draft",
    template_id: independentTemplate.id,
    template_version: "1.0.0",
    sources: [
      {
        run_id: "r1",
        summary_hash: "b".repeat(64),
        assessment_id: assessmentId,
        assessment_revision: 1,
        assessment_hash: "f".repeat(64),
      },
    ],
    supersedes_id: null,
    confirmed: true,
  });
  expect(
    screen.getByRole("region", {
      name: "Opened independent historical archive",
    }),
  ).toBeTruthy();
  expect(
    state.api.mock.calls.some((c: unknown[]) =>
      /independent-assessment|cases|gold|output|assistant|execute/.test(
        String(c[0]),
      ),
    ),
  ).toBe(false);
});
it("renders provisional historical revisions but refuses staging; loading never auto-selects latest", async () => {
  state.api.mockImplementation((route: string) =>
    route.includes("/assessments/")
      ? assessmentArchive({ assessment: provisionalAssessment() })
      : response(route),
  );
  mount();
  await load();
  await source();
  expect(
    screen.getByRole<HTMLButtonElement>("button", {
      name: "Add independent report component",
    }).disabled,
  ).toBe(true);
  expect(
    screen.getByText(/Provisional assessments are ineligible/),
  ).toBeTruthy();
});
it("double-clicks cannot resend; 404/unknown remain same-ID GET across project switches and late completion", async () => {
  const pending: PendingIndependentArchives = new Map();
  const view = mount("report", pending);
  await prepare();
  confirm();
  let rejectWrite!: (e: Error) => void;
  state.api.mockImplementation((route: string, body?: unknown) =>
    body
      ? new Promise((_, reject) => {
          rejectWrite = reject;
        })
      : response(route),
  );
  await act(async () => {
    fireEvent.click(
      screen.getByRole("button", { name: "Create independent report draft" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Create independent report draft" }),
    );
  });
  const remembered = pending.get(independentPendingKey("p1", "report"))!;
  expect(remembered).toBeTruthy();
  expect(writes()).toHaveLength(1);
  view.rerender(
    <IndependentArchiveWorkspace
      key="p2"
      kind="report"
      projectId="p2"
      zh={false}
      pendingArchives={pending}
      writeLock={view.writeLock}
    />,
  );
  await act(async () => rejectWrite(new Error("uncertain")));
  expect(pending.size).toBe(1);
  expect(screen.queryByRole("status")).toBeNull();
  view.rerender(
    <IndependentArchiveWorkspace
      key="p1"
      kind="report"
      projectId="p1"
      zh={false}
      pendingArchives={pending}
      writeLock={view.writeLock}
    />,
  );
  state.api.mockRejectedValueOnce(new Error("404"));
  await click("Check same-ID independent archive receipt");
  expect(pending.size).toBe(1);
  expect(writes()).toHaveLength(1);
  state.api.mockImplementation(response);
  await click("Check same-ID independent archive receipt");
  expect(pending.size).toBe(0);
  expect(writes()).toHaveLength(1);
  expect(state.api.mock.calls.at(-1)![0]).toContain(remembered.id);
});
it("rejects substituted receipt source and retains the original pending ID", async () => {
  const view = mount();
  await prepare();
  confirm();
  state.api.mockImplementation((route: string, body?: unknown) =>
    body
      ? {
          ...response(route, body),
          components: [
            {
              ...independentReport().components[0],
              assessment_ref: {
                assessment_id: assessmentId,
                assessment_revision: 2,
                assessment_hash: "f".repeat(64),
              },
            },
          ],
        }
      : response(route),
  );
  await click("Create independent report draft");
  expect(view.pending.size).toBe(1);
  expect(screen.getByRole("alert")).toBeTruthy();
  expect(
    screen.queryByRole("region", {
      name: "Opened independent historical archive",
    }),
  ).toBeNull();
});
it("pins retest sides separately and opens the server comparison without sensitive paired reads", async () => {
  mount("retest");
  await load();
  await source();
  await click("Use as historical baseline");
  await source("r2");
  await click("Use as historical retest");
  confirm();
  await click("Create independent retest comparison");
  expect(writes()).toHaveLength(1);
  expect(
    screen.getByRole("region", {
      name: "Opened independent historical archive",
    }).textContent,
  ).toContain("All-sample pass-rate delta: 0 / 2");
});
it("revokes confirmation on edits and refresh and treats archive text literally", async () => {
  mount();
  await prepare();
  confirm();
  fireEvent.change(screen.getByLabelText("Independent report title"), {
    target: { value: "changed" },
  });
  expect(screen.getByRole<HTMLInputElement>("checkbox").checked).toBe(false);
  confirm();
  await load();
  expect(screen.getByRole<HTMLInputElement>("checkbox").checked).toBe(false);
  const literal =
    '<img src="https://invalid.example/pixel"> https://invalid.example';
  state.api.mockImplementation((route: string) =>
    route.includes("archives/")
      ? { ...response(route), markdown: literal }
      : response(route),
  );
  fireEvent.change(screen.getByLabelText("Known independent archive ID"), {
    target: { value: "a".repeat(32) },
  });
  await click("Open pinned independent archive");
  const region = screen.getByRole("region", {
    name: "Opened independent historical archive",
  });
  expect(region.textContent).toContain(literal);
  expect(region.querySelector("img,a")).toBeNull();
});

it("exports only an explicitly opened independent historical report, once, with the viewed receipt", async () => {
  const blob = new Blob([new Uint8Array([80, 75, 3, 4])]);
  state.word.mockResolvedValue(blob);
  const createUrl = rs
    .spyOn(URL, "createObjectURL")
    .mockReturnValue("blob:independent");
  const revokeUrl = rs
    .spyOn(URL, "revokeObjectURL")
    .mockImplementation(() => undefined);
  const save = rs
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => undefined);
  try {
    mount();
    await prepare();
    expect(state.word).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("checkbox"));
    await click("Create independent report draft");
    const id = (writes()[0]![0] as string).split("/").at(-1)!;
    const count = writes().length;
    await click("Download independent historical Word draft");
    expect(state.word).toHaveBeenCalledTimes(1);
    expect(state.word).toHaveBeenCalledWith(
      `evaluation/projects/p1/independent-report-archives/${id}/exports/independent-qa-docx-v1?archive_hash=${"c".repeat(64)}`,
    );
    expect(createUrl).toHaveBeenCalledWith(blob);
    expect(save).toHaveBeenCalledTimes(1);
    expect(writes()).toHaveLength(count);
  } finally {
    createUrl.mockRestore();
    revokeUrl.mockRestore();
    save.mockRestore();
  }
});
it("late Word responses after scope unmount never create a download", async () => {
  let resolve!: (value: Blob) => void;
  state.word.mockImplementation(
    () =>
      new Promise<Blob>((done) => {
        resolve = done;
      }),
  );
  const createUrl = rs
    .spyOn(URL, "createObjectURL")
    .mockReturnValue("blob:late");
  try {
    const mounted = mount();
    await prepare();
    fireEvent.click(screen.getByRole("checkbox"));
    await click("Create independent report draft");
    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", {
          name: "Download independent historical Word draft",
        }),
      );
      fireEvent.click(
        screen.getByRole("button", {
          name: "Download independent historical Word draft",
        }),
      );
    });
    expect(state.word).toHaveBeenCalledTimes(1);
    mounted.unmount();
    await act(async () => {
      resolve(new Blob(["late"]));
    });
    expect(createUrl).not.toHaveBeenCalled();
  } finally {
    createUrl.mockRestore();
  }
});
it("failed Word export shows a generic error, retains the archive, and never retries", async () => {
  state.word.mockRejectedValue(new Error("PRIVATE_RESPONSE"));
  mount();
  await prepare();
  fireEvent.click(screen.getByRole("checkbox"));
  await click("Create independent report draft");
  await click("Download independent historical Word draft");
  expect(state.word).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("alert").textContent).not.toContain(
    "PRIVATE_RESPONSE",
  );
  expect(
    screen.getByRole("region", {
      name: "Opened independent historical archive",
    }),
  ).toBeTruthy();
});

it("exports only an explicitly opened independent historical retest, once, with the viewed receipt", async () => {
  const blob = new Blob([new Uint8Array([80, 75, 3, 4])]);
  state.retestWord.mockResolvedValue(blob);
  const createUrl = rs
    .spyOn(URL, "createObjectURL")
    .mockReturnValue("blob:independent");
  const revokeUrl = rs
    .spyOn(URL, "revokeObjectURL")
    .mockImplementation(() => undefined);
  const save = rs
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => undefined);
  try {
    mount("retest");
    await load();
    await source();
    await click("Use as historical baseline");
    await source("r2");
    await click("Use as historical retest");
    expect(state.retestWord).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("checkbox"));
    await click("Create independent retest comparison");
    const id = (writes()[0]![0] as string).split("/").at(-1)!;
    const count = writes().length;
    await click("Download independent historical retest Word draft");
    expect(state.retestWord).toHaveBeenCalledTimes(1);
    expect(state.word).not.toHaveBeenCalled();
    expect(state.retestWord).toHaveBeenCalledWith(
      `evaluation/projects/p1/independent-retest-archives/${id}/exports/independent-retest-docx-v1?archive_hash=${"c".repeat(64)}`,
    );
    expect(createUrl).toHaveBeenCalledWith(blob);
    expect(save).toHaveBeenCalledTimes(1);
    expect(writes()).toHaveLength(count);
  } finally {
    createUrl.mockRestore();
    revokeUrl.mockRestore();
    save.mockRestore();
  }
});
it("late retest Word responses after scope unmount never create a download", async () => {
  let resolve!: (value: Blob) => void;
  state.retestWord.mockImplementation(
    () =>
      new Promise<Blob>((done) => {
        resolve = done;
      }),
  );
  const createUrl = rs
    .spyOn(URL, "createObjectURL")
    .mockReturnValue("blob:late");
  try {
    const mounted = mount("retest");
    await load();
    await source();
    await click("Use as historical baseline");
    await source("r2");
    await click("Use as historical retest");
    fireEvent.click(screen.getByRole("checkbox"));
    await click("Create independent retest comparison");
    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", {
          name: "Download independent historical retest Word draft",
        }),
      );
      fireEvent.click(
        screen.getByRole("button", {
          name: "Download independent historical retest Word draft",
        }),
      );
    });
    expect(state.retestWord).toHaveBeenCalledTimes(1);
    expect(state.word).not.toHaveBeenCalled();
    mounted.unmount();
    await act(async () => {
      resolve(new Blob(["late"]));
    });
    expect(createUrl).not.toHaveBeenCalled();
  } finally {
    createUrl.mockRestore();
  }
});
it("failed retest Word export shows a generic error, retains the archive, and never retries", async () => {
  state.retestWord.mockRejectedValue(new Error("PRIVATE_RESPONSE"));
  mount("retest");
  await load();
  await source();
  await click("Use as historical baseline");
  await source("r2");
  await click("Use as historical retest");
  fireEvent.click(screen.getByRole("checkbox"));
  await click("Create independent retest comparison");
  await click("Download independent historical retest Word draft");
  expect(state.retestWord).toHaveBeenCalledTimes(1);
  expect(state.word).not.toHaveBeenCalled();
  expect(screen.getByRole("alert").textContent).not.toContain(
    "PRIVATE_RESPONSE",
  );
  expect(
    screen.getByRole("region", {
      name: "Opened independent historical archive",
    }),
  ).toBeTruthy();
});

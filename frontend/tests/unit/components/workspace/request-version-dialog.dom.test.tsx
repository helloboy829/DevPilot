import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { RequestVersionDialog } from "@/components/workspace/request-version-dialog";

const state = rs.hoisted(() => ({ api: rs.fn() }));
rs.mock("@/core/evaluation/api", () => ({ evaluationApi: state.api }));
const request = {
  method: "POST",
  url: "https://example.test/private?key=SYNTHETIC_QUERY",
  headers: [["Authorization", "Bearer SYNTHETIC_TOKEN"]],
  body: '{"q":"SYNTHETIC_BODY"}',
};
const version = {
  id: "v1",
  project_id: "p1",
  component_id: "c1",
  version_label: "v1",
  scope: "request_definition_only",
  protected_hash: "a".repeat(64),
  created_by: "owner",
  created_at: "2026-11-08T00:00:00Z",
  request_template: {
    schema: "request-template.v1",
    method: "POST",
    origin: "https://example.test:443",
    headers: [["Authorization", "DEVPILOT_REQUEST_HEADER_1"]],
    fingerprint: "b".repeat(64),
  },
};
const consent = /I confirm encrypted storage/;

beforeEach(() => {
  state.api.mockReset();
  state.api.mockImplementation(async (route: string, payload?: unknown) => {
    if (route === "evaluation/projects")
      return {
        projects: [
          { id: "p1", name: "Project one" },
          { id: "p2", name: "Project two" },
        ],
      };
    if (route.endsWith("/components"))
      return {
        components: [
          { id: "c1", name_at_link: "Fixture component", kind: "llm" },
        ],
      };
    if (route.endsWith("/request-versions"))
      return payload ? version : { request_versions: [version] };
    throw new Error("Unexpected route");
  });
});
afterEach(cleanup);
async function selectScope() {
  fireEvent.click(
    screen.getByRole("button", { name: "Load / refresh projects" }),
  );
  await screen.findByRole("option", { name: "Project one" });
  fireEvent.change(screen.getByLabelText("Project"), {
    target: { value: "p1" },
  });
  await screen.findByRole("option", { name: /Fixture component/ });
  fireEvent.change(screen.getByLabelText("Project component"), {
    target: { value: "c1" },
  });
}
async function ready() {
  await selectScope();
  fireEvent.change(screen.getByLabelText("Request version label"), {
    target: { value: "v1" },
  });
  fireEvent.click(screen.getByRole("checkbox", { name: consent }));
}

describe("request version intake", () => {
  it("loads only explicitly, stores the exact reviewed request, and does not send it", async () => {
    render(
      <RequestVersionDialog request={request} zh={false} onClose={rs.fn()} />,
    );
    expect(state.api).not.toHaveBeenCalled();
    expect(screen.getByText(/Saving is not execution approval/)).toBeTruthy();
    expect(screen.queryByText(/SYNTHETIC_TOKEN/)).toBeNull();
    await ready();
    fireEvent.click(
      screen.getByRole("button", { name: "Save encrypted version" }),
    );
    await screen.findByRole("status");
    expect(state.api).toHaveBeenCalledWith(
      "evaluation/projects/p1/components/c1/request-versions",
      { version_label: "v1", confirmed: true, request },
    );
    expect(
      state.api.mock.calls.every(([route]) => !String(route).includes("/send")),
    ).toBe(true);
    expect(
      screen.getByRole<HTMLInputElement>("checkbox", { name: consent }).checked,
    ).toBe(false);
    expect(screen.getByText("v1", { selector: "strong" })).toBeTruthy();
  });
  it("revokes consent on field edits and scope changes and clears stale metadata", async () => {
    render(
      <RequestVersionDialog request={request} zh={false} onClose={rs.fn()} />,
    );
    await ready();
    fireEvent.change(screen.getByLabelText("Request version label"), {
      target: { value: "v2" },
    });
    expect(
      screen.getByRole<HTMLInputElement>("checkbox", { name: consent }).checked,
    ).toBe(false);
    fireEvent.click(
      screen.getByRole("button", { name: "Load saved versions" }),
    );
    await screen.findByText("v1", { selector: "strong" });
    fireEvent.change(screen.getByLabelText("Project"), {
      target: { value: "p2" },
    });
    await waitFor(() =>
      expect(screen.queryByText("v1", { selector: "strong" })).toBeNull(),
    );
    expect(
      screen.getByLabelText<HTMLSelectElement>("Project component").value,
    ).toBe("");
    expect(
      screen.getByLabelText<HTMLInputElement>("Request version label").value,
    ).toBe("");
  });
  it("retains fields, hides raw errors and requires fresh confirmation after a failed write", async () => {
    render(
      <RequestVersionDialog request={request} zh={false} onClose={rs.fn()} />,
    );
    await ready();
    state.api.mockRejectedValueOnce(new Error("SYNTHETIC_TOKEN_INTERNAL"));
    fireEvent.click(
      screen.getByRole("button", { name: "Save encrypted version" }),
    );
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Could not save");
    expect(alert.textContent).not.toContain("SYNTHETIC_TOKEN");
    expect(
      screen.getByLabelText<HTMLInputElement>("Request version label").value,
    ).toBe("v1");
    expect(
      screen.getByRole<HTMLInputElement>("checkbox", { name: consent }).checked,
    ).toBe(false);
    expect(
      screen
        .getByRole("button", { name: "Save encrypted version" })
        .hasAttribute("disabled"),
    ).toBe(true);
  });
  it("locks duplicate writes, scope edits and dismissal while saving", async () => {
    const close = rs.fn();
    render(
      <RequestVersionDialog request={request} zh={false} onClose={close} />,
    );
    await ready();
    let resolve!: (v: unknown) => void;
    state.api.mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    const button = screen.getByRole("button", {
      name: "Save encrypted version",
    });
    fireEvent.click(button);
    fireEvent.submit(button.closest("form")!);
    expect(
      state.api.mock.calls.filter(([, body]) => body !== undefined),
    ).toHaveLength(1);
    expect(screen.getByLabelText("Project").closest("fieldset")!.disabled).toBe(
      true,
    );
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(close).not.toHaveBeenCalled();
    await act(async () => resolve(version));
    await screen.findByRole("status");
  });
  it("supports a read-only metadata viewer, with no plaintext retrieval or save control", async () => {
    render(
      <RequestVersionDialog request={null} zh={false} onClose={rs.fn()} />,
    );
    await selectScope();
    fireEvent.click(
      screen.getByRole("button", { name: "Load saved versions" }),
    );
    await screen.findByText("v1", { selector: "strong" });
    expect(
      screen.queryByRole("button", { name: "Save encrypted version" }),
    ).toBeNull();
    expect(state.api.mock.calls.every(([, body]) => body === undefined)).toBe(
      true,
    );
    expect(screen.queryByText(/SYNTHETIC_BODY/)).toBeNull();
    expect(screen.getByText("https://example.test:443")).toBeTruthy();
  });
  it("rejects a mismatched save response instead of reporting success", async () => {
    render(
      <RequestVersionDialog request={request} zh={false} onClose={rs.fn()} />,
    );
    await ready();
    state.api.mockResolvedValueOnce({
      ...version,
      component_id: "another-component",
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Save encrypted version" }),
    );
    await screen.findByRole("alert");
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByText("v1", { selector: "strong" })).toBeNull();
  });
  it("filters metadata from a different project or scope", async () => {
    render(
      <RequestVersionDialog request={null} zh={false} onClose={rs.fn()} />,
    );
    await selectScope();
    state.api.mockResolvedValueOnce({
      request_versions: [
        { ...version, project_id: "p2" },
        { ...version, scope: "execution" },
      ],
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Load saved versions" }),
    );
    await screen.findByText("No saved versions.");
    expect(screen.queryByText("v1", { selector: "strong" })).toBeNull();
  });
  it("does not show a success for another scope after unmount", async () => {
    const view = render(
      <RequestVersionDialog request={request} zh={false} onClose={rs.fn()} />,
    );
    await ready();
    let resolve!: (v: unknown) => void;
    state.api.mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Save encrypted version" }),
    );
    view.unmount();
    await act(async () => resolve(version));
    expect(screen.queryByRole("status")).toBeNull();
  });
});

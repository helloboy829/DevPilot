import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { ManualAssistantDialog } from "@/components/workspace/agents/manual-assistant-dialog";

const state = rs.hoisted(() => ({ mutateAsync: rs.fn() }));
rs.mock("@/core/agents", () => ({
  useCreateAgent: () => ({ mutateAsync: state.mutateAsync }),
}));
rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ locale: "en-US" }) }));

beforeEach(() => {
  state.mutateAsync.mockReset();
});
afterEach(cleanup);
function fill() {
  fireEvent.change(screen.getByLabelText("Assistant name"), {
    target: { value: "MY-ADVISOR" },
  });
  fireEvent.change(screen.getByLabelText("Role preset"), {
    target: { value: "requirements" },
  });
}

describe("manual assistant configuration", () => {
  it("saves a reviewed configuration without a model call and closes only on success", async () => {
    const close = rs.fn();
    state.mutateAsync.mockResolvedValue({});
    render(<ManualAssistantDialog onClose={close} />);
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Save assistant" }));
    await waitFor(() => expect(close).toHaveBeenCalledTimes(1));
    expect(state.mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "my-advisor",
        model: null,
        skills: [],
        tool_groups: [],
      }),
    );
  });

  it("keeps fields and a visible error on failure", async () => {
    state.mutateAsync.mockImplementation(async () => {
      throw new Error("SYNTHETIC_INTERNAL_DETAIL");
    });
    const close = rs.fn();
    render(<ManualAssistantDialog onClose={close} />);
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Save assistant" }));
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain("Could not save"),
    );
    expect(screen.getByRole("alert").textContent).not.toContain(
      "SYNTHETIC_INTERNAL_DETAIL",
    );
    expect(
      screen.getByLabelText<HTMLInputElement>("Assistant name").value,
    ).toBe("MY-ADVISOR");
    expect(close).not.toHaveBeenCalled();
  });

  it("locks edits, duplicate submits and dismissal until the request settles", async () => {
    let resolve!: (value: unknown) => void;
    state.mutateAsync.mockImplementation(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    const close = rs.fn();
    render(<ManualAssistantDialog onClose={close} />);
    fill();
    const submit = screen.getByRole("button", { name: "Save assistant" });
    fireEvent.click(submit);
    fireEvent.submit(submit.closest("form")!);
    expect(state.mutateAsync).toHaveBeenCalledTimes(1);
    expect(
      screen.getByLabelText("Assistant name").closest("fieldset")!.disabled,
    ).toBe(true);
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(close).not.toHaveBeenCalled();
    await act(async () => resolve({}));
    await waitFor(() => expect(close).toHaveBeenCalledTimes(1));
  });

  it("rejects invalid fields locally", async () => {
    render(<ManualAssistantDialog onClose={rs.fn()} />);
    fill();
    fireEvent.change(screen.getByLabelText("Assistant name"), {
      target: { value: "invalid_name" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save assistant" }));
    expect(screen.getByRole("alert").textContent).toContain("1–64");
    expect(state.mutateAsync).not.toHaveBeenCalled();
  });
});

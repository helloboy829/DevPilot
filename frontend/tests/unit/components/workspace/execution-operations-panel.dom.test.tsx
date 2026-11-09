import { afterEach, beforeEach, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";

import { ExecutionOperationsPanel } from "@/components/workspace/execution-operations-panel";
import type { User } from "@/core/auth/types";

import fixture from "../../../fixtures/reservation-snapshot";

const state = rs.hoisted(() => ({
  load: rs.fn(),
  user: null as User | null,
  loading: false,
}));
rs.mock("@/core/evaluation/execution-operations", () => ({
  reservationStates: [
    "queued",
    "running",
    "cancel_requested",
    "collected",
    "interrupted",
  ],
  loadReservationSnapshot: state.load,
}));
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({
    user: state.user,
    isAuthenticated: state.user !== null,
    isLoading: state.loading,
  }),
}));
const admin = (id = "admin-a"): User => ({
  id,
  email: `${id}@test.local`,
  system_role: "admin",
  needs_setup: false,
});
beforeEach(() => {
  state.user = admin();
  state.loading = false;
  state.load.mockReset();
  state.load.mockResolvedValue(fixture);
});
afterEach(cleanup);
const button = () =>
  screen.getByRole("button", { name: "Load reservation snapshot" });
function deferred() {
  let resolve!: (value: typeof fixture) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<typeof fixture>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
it("does not load on mount or locale change; loads only explicit aggregate data with warnings", async () => {
  const view = render(<ExecutionOperationsPanel zh={false} />);
  expect(state.load).not.toHaveBeenCalled();
  expect(screen.getByText(/A reached deadline does not prove/)).toBeTruthy();
  expect(
    screen.getByText(/not global agreement or available quota/),
  ).toBeTruthy();
  fireEvent.click(button());
  await screen.findByTestId("reservation-snapshot");
  expect(screen.getByText("70")).toBeTruthy();
  expect(screen.getByText(/Interrupted: 1/)).toBeTruthy();
  view.rerender(<ExecutionOperationsPanel zh />);
  expect(screen.getByText(/仅响应进程的策略/)).toBeTruthy();
  expect(state.load).toHaveBeenCalledTimes(1);
  expect(screen.getAllByRole("button")).toHaveLength(1);
});
it("locks synchronous duplicate clicks and clears an old snapshot before explicit reload", async () => {
  render(<ExecutionOperationsPanel zh={false} />);
  fireEvent.click(button());
  await screen.findByTestId("reservation-snapshot");
  const pending = deferred();
  state.load.mockReturnValue(pending.promise);
  const target = button();
  act(() => {
    fireEvent.click(target);
    fireEvent.click(target);
  });
  expect(state.load).toHaveBeenCalledTimes(2);
  expect(screen.queryByTestId("reservation-snapshot")).toBeNull();
  expect(target.hasAttribute("disabled")).toBe(true);
  await act(async () => {
    pending.resolve(fixture);
    await pending.promise;
  });
  expect(target.hasAttribute("disabled")).toBe(false);
});
it.each(["account", "role", "logout", "refresh", "unmount"])(
  "fences pending results and aborts GET on %s changes",
  async (change) => {
    const pending = deferred();
    state.load.mockReturnValueOnce(pending.promise);
    const view = render(<ExecutionOperationsPanel zh={false} />);
    fireEvent.click(button());
    const signal = state.load.mock.calls[0]?.[0] as AbortSignal;
    if (change === "account") state.user = admin("admin-b");
    if (change === "role") state.user = { ...admin(), system_role: "user" };
    if (change === "logout") state.user = null;
    if (change === "refresh") state.loading = true;
    if (change === "unmount") view.unmount();
    else view.rerender(<ExecutionOperationsPanel zh={false} />);
    expect(signal.aborted).toBe(true);
    expect(screen.queryByTestId("reservation-snapshot")).toBeNull();
    await act(async () => {
      pending.resolve(fixture);
      await pending.promise;
    });
    expect(screen.queryByTestId("reservation-snapshot")).toBeNull();
    expect(state.load).toHaveBeenCalledTimes(1);
  },
);
it("hides already loaded data immediately at account/role loss without fetching", async () => {
  const view = render(<ExecutionOperationsPanel zh={false} />);
  fireEvent.click(button());
  await screen.findByTestId("reservation-snapshot");
  state.user = admin("admin-b");
  view.rerender(<ExecutionOperationsPanel zh={false} />);
  expect(screen.queryByTestId("reservation-snapshot")).toBeNull();
  state.user = { ...admin("admin-b"), system_role: "user" };
  view.rerender(<ExecutionOperationsPanel zh={false} />);
  expect(screen.queryByRole("button")).toBeNull();
  expect(state.load).toHaveBeenCalledTimes(1);
});
it("does not restore a prior snapshot or late errors after same-ID logout/login", async () => {
  const pending = deferred();
  state.load.mockReturnValueOnce(pending.promise);
  const view = render(<ExecutionOperationsPanel zh={false} />);
  fireEvent.click(button());
  state.user = null;
  view.rerender(<ExecutionOperationsPanel zh={false} />);
  state.user = admin();
  view.rerender(<ExecutionOperationsPanel zh={false} />);
  fireEvent.click(button());
  await screen.findByTestId("reservation-snapshot");
  await act(async () => {
    pending.reject(new Error("SECRET-SENTINEL"));
    await pending.promise.catch(() => undefined);
  });
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.getByTestId("reservation-snapshot")).toBeTruthy();
  expect(state.load).toHaveBeenCalledTimes(2);
});
it("shows only generic errors, never retries, and permits a new manual read", async () => {
  state.load.mockRejectedValueOnce(new Error("SECRET-SENTINEL"));
  render(<ExecutionOperationsPanel zh={false} />);
  fireEvent.click(button());
  expect((await screen.findByRole("alert")).textContent).not.toContain(
    "SECRET-SENTINEL",
  );
  expect(state.load).toHaveBeenCalledTimes(1);
  expect(screen.queryByTestId("reservation-snapshot")).toBeNull();
  fireEvent.click(button());
  await screen.findByTestId("reservation-snapshot");
  expect(screen.queryByRole("alert")).toBeNull();
  expect(state.load).toHaveBeenCalledTimes(2);
});
it.each([null, { ...admin(), system_role: "user" as const }])(
  "has no diagnostic request or controls for non-admin identity",
  (user) => {
    state.user = user;
    render(<ExecutionOperationsPanel zh={false} />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(state.load).not.toHaveBeenCalled();
  },
);

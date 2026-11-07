import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";

import {
  WorkspaceStyleProvider,
  useWorkspaceStyle,
} from "@/core/appearance/provider";
import { WORKSPACE_STYLE_STORAGE_KEY as KEY } from "@/core/appearance/styles";
const route = rs.hoisted(() => ({ path: "/workspace/evaluations" }));
rs.mock("next/navigation", () => ({ usePathname: () => route.path }));
function Consumer() {
  const { style, setStyle } = useWorkspaceStyle();
  return (
    <>
      <output>{style}</output>
      <button onClick={() => setStyle("forest")}>select</button>
    </>
  );
}
const view = () => (
  <WorkspaceStyleProvider>
    <Consumer />
  </WorkspaceStyleProvider>
);
beforeEach(() => {
  localStorage.clear();
  route.path = "/workspace/evaluations";
});
afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
});
describe("workspace style boundary", () => {
  it("restores a validated preference, syncs other tabs and cleans up its root attribute", () => {
    localStorage.setItem(KEY, "paper");
    const rendered = render(view());
    expect(screen.getByText("paper")).toBeTruthy();
    expect(document.documentElement.dataset.workspaceStyle).toBe("paper");
    act(() => {
      window.dispatchEvent(
        new StorageEvent("storage", { key: KEY, newValue: "violet" }),
      );
    });
    expect(screen.getByText("violet")).toBeTruthy();
    act(() => {
      window.dispatchEvent(
        new StorageEvent("storage", { key: KEY, newValue: "bad-value" }),
      );
    });
    expect(screen.getByText("console")).toBeTruthy();
    rendered.unmount();
    expect(document.documentElement.dataset.workspaceStyle).toBeUndefined();
  });
  it("keeps selection usable if browser storage is denied", () => {
    rs.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    rs.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    render(view());
    fireEvent.click(screen.getByRole("button", { name: "select" }));
    expect(screen.getByText("forest")).toBeTruthy();
    expect(document.documentElement.dataset.workspaceStyle).toBe("forest");
  });
  it("does not restyle public/login routes or carry account data", () => {
    const rendered = render(view());
    fireEvent.click(screen.getByRole("button", { name: "select" }));
    expect(localStorage.getItem(KEY)).toBe("forest");
    route.path = "/login";
    rendered.rerender(view());
    expect(document.documentElement.dataset.workspaceStyle).toBeUndefined();
    route.path = "/workspace/reports";
    rendered.rerender(view());
    expect(document.documentElement.dataset.workspaceStyle).toBe("forest");
  });
});

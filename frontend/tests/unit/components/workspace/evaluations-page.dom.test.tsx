import { afterEach, expect, it, rs } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    locale: "en-US",
    t: {
      workspace: { githubTooltip: "GitHub" },
      breadcrumb: { workspace: "Workspace" },
      sidebar: { reports: "Reports" },
      common: { home: "Home" },
    },
  }),
}));
rs.mock("@/core/component-tests/hooks", () => ({
  useComponents: () => ({
    data: [],
    isFetching: false,
    isPending: false,
    isError: false,
    refetch: rs.fn(),
  }),
}));
rs.mock("@/components/ui/sidebar", () => ({ SidebarTrigger: () => null }));

import EvaluationHome from "@/app/workspace/evaluations/page";

afterEach(() => cleanup());

it("links to the ledger-only performance workbench separately from results", () => {
  render(<EvaluationHome />);
  expect(
    screen
      .getByRole("link", { name: "Open performance workbench" })
      .getAttribute("href"),
  ).toBe("/workspace/performance");
  expect(
    screen
      .getByRole("link", { name: "Browse performance results" })
      .getAttribute("href"),
  ).toBe("/workspace/performance-results");
  expect(
    screen.getByText(/no Worker or requests are dispatched/i),
  ).toBeTruthy();
});

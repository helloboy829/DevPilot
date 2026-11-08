import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, render, screen, waitFor } from "@testing-library/react";

import { CodeBlock } from "@/components/ai-elements/code-block";

const state = rs.hoisted(() => ({
  codeToHtml: rs.fn(async () => {
    throw new Error("highlighter unavailable");
  }),
}));
rs.mock("shiki", () => ({ codeToHtml: state.codeToHtml }));
afterEach(cleanup);

describe("CodeBlock", () => {
  it("shows raw code immediately and retains it after asynchronous highlighter failure", async () => {
    // Component import belongs to suite setup, not the fallback's timing budget.
    // Keep the real lazy highlighting helper and reject its Shiki dependency.
    render(<CodeBlock code="const immediate = true" language="typescript" />);
    expect(screen.getByText("const immediate = true")).toBeTruthy();
    await waitFor(() => expect(state.codeToHtml).toHaveBeenCalledTimes(1));
    expect(screen.getByText("const immediate = true")).toBeTruthy();
  });
});

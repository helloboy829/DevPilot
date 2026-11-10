import { afterEach, expect, it, rs } from "@rstest/core";

import { externalQAApi } from "@/core/evaluation/external-qa-api";

const state = rs.hoisted(() => ({ fetch: rs.fn() }));
rs.mock("@/core/api/fetcher", () => ({ fetch: state.fetch }));
rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "https://gateway.test",
}));
afterEach(() => {
  state.fetch.mockReset();
});
it("uses authenticated no-store GET and JSON PUT exactly once", async () => {
  state.fetch.mockImplementation(
    async () =>
      new Response('{"ok":true}', {
        headers: { "Content-Type": "application/json" },
      }),
  );
  const controller = new AbortController();
  expect(
    await externalQAApi(
      "evaluation/projects/p/exports/one",
      undefined,
      controller.signal,
    ),
  ).toEqual({ ok: true });
  expect(state.fetch.mock.calls[0]).toEqual([
    "https://gateway.test/api/evaluation/projects/p/exports/one",
    { method: "GET", cache: "no-store", signal: controller.signal },
  ]);
  await externalQAApi("evaluation/projects/p/external-qa-intakes/one", {
    confirmed: true,
  });
  expect(state.fetch.mock.calls[1]?.[1]).toMatchObject({
    method: "PUT",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: '{"confirmed":true}',
  });
  expect(state.fetch).toHaveBeenCalledTimes(2);
});
it("bounds serialized UTF-8 request before sending", async () => {
  await expect(
    externalQAApi("unused", { raw: "中".repeat(11000) }),
  ).rejects.toThrow();
  expect(state.fetch).not.toHaveBeenCalled();
});
it.each(["text/html", "application/octet-stream"])(
  "rejects successful wrong MIME %s",
  async (mime) => {
    state.fetch.mockResolvedValue(
      new Response("{}", { headers: { "Content-Type": mime } }),
    );
    await expect(externalQAApi("unused")).rejects.toThrow();
    expect(state.fetch).toHaveBeenCalledTimes(1);
  },
);
it("rejects oversized/invalid declared lengths before reading", async () => {
  for (const length of ["262145", "-1", "NaN", "1.5"]) {
    const getReader = rs.fn();
    state.fetch.mockResolvedValue({
      ok: true,
      headers: new Headers({
        "Content-Type": "application/json",
        "Content-Length": length,
      }),
      body: { getReader },
    });
    await expect(externalQAApi("unused")).rejects.toThrow();
    expect(getReader).not.toHaveBeenCalled();
  }
});
it("bounds streamed bytes and cancels oversized or invalid UTF-8 reads", async () => {
  for (const chunks of [[new Uint8Array(262145)], [new Uint8Array([0xff])]]) {
    const cancel = rs.fn(),
      releaseLock = rs.fn();
    let index = 0;
    state.fetch.mockResolvedValue({
      ok: true,
      headers: new Headers({ "Content-Type": "application/json" }),
      body: {
        getReader: () => ({
          read: async () =>
            index < chunks.length
              ? { done: false, value: chunks[index++] }
              : { done: true },
          cancel,
          releaseLock,
        }),
      },
    });
    await expect(externalQAApi("unused")).rejects.toThrow();
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(releaseLock).toHaveBeenCalledTimes(1);
  }
});
it("unknown HTTP outcomes never read sensitive errors or retry", async () => {
  const text = rs.fn(),
    json = rs.fn();
  state.fetch.mockResolvedValue({ ok: false, status: 404, text, json });
  await expect(externalQAApi("unused", { confirmed: true })).rejects.toThrow(
    "External metadata operation unavailable",
  );
  expect(state.fetch).toHaveBeenCalledTimes(1);
  expect(text).not.toHaveBeenCalled();
  expect(json).not.toHaveBeenCalled();
});
it("rejects mismatched actual content length and malformed successful JSON", async () => {
  for (const response of [
    new Response("{}", {
      headers: { "Content-Type": "application/json", "Content-Length": "3" },
    }),
    new Response("not JSON", {
      headers: { "Content-Type": "application/json" },
    }),
  ]) {
    state.fetch.mockResolvedValue(response);
    await expect(externalQAApi("unused")).rejects.toThrow();
  }
});

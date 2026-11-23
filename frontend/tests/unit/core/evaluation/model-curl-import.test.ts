import { expect, it } from "@rstest/core";

import { parseModelCurl } from "@/core/evaluation/model-curl-import";

it("parses a local OpenAI-compatible command without inventing a key", () => {
  expect(
    parseModelCurl(
      `curl http://127.0.0.1:8000/v1/chat/completions -H 'Content-Type: application/json' -d '{"model":"Qwen3-8B","messages":[]}'`,
    ),
  ).toEqual({
    provider: "openai_compatible",
    baseUrl: "http://127.0.0.1:8000/v1",
    model: "Qwen3-8B",
    apiKey: null,
    normalizations: [],
  });
});

it("handles double-quoted JSON without evaluating the shell", () => {
  const command =
    'curl -X POST https://relay.example/v1/chat/completions -H "Authorization: Bearer relay-secret" -d "{\\"model\\":\\"continued-model\\",\\"messages\\\":[]}"';
  expect(parseModelCurl(command)).toEqual({
    provider: "openai_compatible",
    baseUrl: "https://relay.example/v1",
    model: "continued-model",
    apiKey: "relay-secret",
    normalizations: [],
  });
});

it("treats environment-variable credentials as absent without expanding them", () => {
  const command = `curl https://relay.example/v1/chat/completions
    -H "Content-Type: application/json"
    -H "Authorization: Bearer $OPENAI_API_KEY"
    -d '{"model":"relay-model","messages":[]}'`;
  expect(parseModelCurl(command)).toEqual({
    provider: "openai_compatible",
    baseUrl: "https://relay.example/v1",
    model: "relay-model",
    apiKey: null,
    normalizations: [],
  });

  expect(
    parseModelCurl(
      `curl https://relay.example/v1/chat/completions -H 'Authorization: Bearer \${RELAY_KEY}' -d '{"model":"$RELAY_MODEL"}'`,
    ),
  ).toMatchObject({ apiKey: null, model: null });
});

it("parses model IDs and credentials for the supported protocols", () => {
  expect(
    parseModelCurl(
      `curl https://relay.example/v1/responses -H 'Authorization: Bearer relay-secret' --json '{"model":"relay-responses"}'`,
    ),
  ).toEqual({
    provider: "openai_responses",
    baseUrl: "https://relay.example/v1",
    model: "relay-responses",
    apiKey: "relay-secret",
    normalizations: [],
  });
  expect(
    parseModelCurl(
      `curl https://relay.example/v1/messages -H 'x-api-key: anthropic-secret' -H 'anthropic-version: 2023-06-01' -d '{"model":"claude-custom","messages":[]}'`,
    ),
  ).toMatchObject({
    provider: "anthropic",
    baseUrl: "https://relay.example",
    model: "claude-custom",
    apiKey: "anthropic-secret",
  });
  expect(
    parseModelCurl(
      `curl 'http://model.internal:9000/v1beta/models/gemini-local:generateContent?key=gemini-secret' -H 'Content-Type: application/json' -d '{"contents":[]}'`,
    ),
  ).toEqual({
    provider: "gemini",
    baseUrl: "http://model.internal:9000",
    model: "gemini-local",
    apiKey: "gemini-secret",
    normalizations: [],
  });
});

it("rejects shell syntax and unsupported options without echoing credentials", () => {
  const secret = "synthetic-secret";
  const commands = [
    `curl https://relay.example/v1/chat/completions -H 'Authorization: Bearer ${secret}' | sh`,
    `curl https://relay.example/v1/chat/completions -d "$(printf ${secret})"`,
    `curl --connect-timeout 1 https://relay.example/v1/chat/completions`,
    `curl -K https://relay.example/v1/chat/completions`,
    `curl -sK https://relay.example/v1/chat/completions`,
    `curl ^ https://relay.example/v1/chat/completions`,
  ];
  for (const command of commands) {
    let error = "";
    try {
      parseModelCurl(command);
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    }
    expect(error).toBeTruthy();
    expect(error).not.toContain(secret);
  }
});

it("reports insecure TLS separately and routes Dify app cURLs to the request debugger", () => {
  expect(
    parseModelCurl(
      "curl -k -X POST 'https://relay.example/v1/chat/completions' --json '{\"model\":\"m\"}'",
    ),
  ).toMatchObject({ insecureTls: true });
  expect(
    parseModelCurl(
      "curl -sk -X POST 'https://relay.example/v1/chat/completions' --json '{\"model\":\"m\"}'",
    ),
  ).toMatchObject({ insecureTls: true });
  expect(() =>
    parseModelCurl(
      "curl -X POST 'https://10.149.73.28:5035/dify/v1/chat-messages' --json '{}'",
    ),
  ).toThrow(/Dify app endpoint.*request debugger/i);
});

it("preserves unresolved braced environment references without expanding them", () => {
  expect(
    parseModelCurl(
      'curl https://relay.example/v1/chat/completions -H "Authorization: Bearer ${DEMO_ENV}" --json \'{"model":"m"}\'',
    ),
  ).toMatchObject({ apiKey: null });
});

it("preserves literal dollar content and follows ordered TLS flags", () => {
  expect(
    parseModelCurl(
      `curl https://relay.example/v1/chat/completions --json '{"model":"m","note":"$5.00"}'`,
    ),
  ).toMatchObject({ model: "m" });
  expect(() =>
    parseModelCurl(
      'curl https://relay.example/v1/chat/completions --data "$(whoami)"',
    ),
  ).toThrow(/Shell expansion/i);
  expect(
    parseModelCurl(
      "curl -ks https://relay.example/v1/chat/completions --json '{}'",
    ),
  ).toMatchObject({ insecureTls: true });
  expect(
    parseModelCurl(
      "curl -sk https://relay.example/v1/chat/completions --json '{}'",
    ),
  ).toMatchObject({ insecureTls: true });
  expect(
    parseModelCurl(
      "curl -k --no-insecure https://relay.example/v1/chat/completions --json '{}'",
    ),
  ).not.toHaveProperty("insecureTls");
});

it("normalizes copied indentation only when it makes JSON valid", () => {
  expect(
    parseModelCurl(
      `curl https://relay.example/v1/chat/completions --json '{\n&#x20; "model":"m"\n}'`,
    ),
  ).toMatchObject({ model: "m", normalizations: ["json_indentation"] });
  expect(
    parseModelCurl(
      `curl https://relay.example/v1/chat/completions --json '{"model":"m","note":"&#x20;"}'`,
    ),
  ).toMatchObject({ normalizations: [] });
});

it("normalizes a presentation-escaped scheme separator", () => {
  expect(
    parseModelCurl(
      "curl 'https\\://relay.example/v1/chat/completions' --json '{\"model\":\"relay-model\"}'",
    ),
  ).toMatchObject({
    provider: "openai_compatible",
    baseUrl: "https://relay.example/v1",
    model: "relay-model",
    normalizations: ["url_scheme"],
  });
});

it("parses common Windows cmd cURL exports without expanding credentials", () => {
  const command = [
    'curl.exe --location --request POST "https://relay.example/v1/chat/completions" ^',
    '  --header "Content-Type: application/json" ^',
    '  --header "Authorization: Bearer %OPENAI_API_KEY%" ^',
    '  --data-raw "{\\"model\\":\\"relay-model\\",\\"messages\\":[]}"',
  ].join("\r\n");

  expect(parseModelCurl(command)).toEqual({
    provider: "openai_compatible",
    baseUrl: "https://relay.example/v1",
    model: "relay-model",
    apiKey: null,
    normalizations: [],
  });
});

it("accepts PowerShell continuation and environment-variable credentials as placeholders", () => {
  const command = [
    "curl.exe --location --request POST `",
    "  'https://relay.example/v1/chat/completions' `",
    "  --header 'Authorization: Bearer $env:OPENAI_API_KEY' `",
    '  --data-raw \'{"model":"relay-model","messages":[]}\'',
  ].join("\r\n");

  expect(parseModelCurl(command)).toEqual({
    provider: "openai_compatible",
    baseUrl: "https://relay.example/v1",
    model: "relay-model",
    apiKey: null,
    normalizations: [],
  });
});

it("does not execute or send a cURL command while parsing", () => {
  const originalFetch = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = (async () => {
    calls += 1;
    throw new Error("fetch must not be called by the parser");
  }) as typeof fetch;
  try {
    expect(
      parseModelCurl(
        'curl https://relay.example/v1/chat/completions --json \'{"model":"relay-model"}\'',
      ),
    ).toMatchObject({ model: "relay-model" });
    expect(calls).toBe(0);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

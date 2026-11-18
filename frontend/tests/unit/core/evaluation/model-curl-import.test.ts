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
  });
});

it("rejects shell syntax and unsupported options without echoing credentials", () => {
  const secret = "synthetic-secret";
  const commands = [
    `curl https://relay.example/v1/chat/completions -H 'Authorization: Bearer ${secret}' | sh`,
    `curl https://relay.example/v1/chat/completions -d "$(printf ${secret})"`,
    `curl --connect-timeout 1 https://relay.example/v1/chat/completions`,
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

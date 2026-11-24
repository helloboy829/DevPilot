const MAX_COMMAND_LENGTH = 16_384;
const INVALID_COMMAND =
  "Unable to parse cURL command. Check its syntax and supported options.";
const DIFY_APP_COMMAND =
  "This cURL targets a Dify app endpoint, not a model endpoint. Use the request debugger for Dify chat requests.";
const ENVIRONMENT_REFERENCE =
  /^(?:\$(?:[A-Za-z_][A-Za-z0-9_]*|env:[A-Za-z_][A-Za-z0-9_]*|\{[A-Za-z_][A-Za-z0-9_]*\}|\{env:[A-Za-z_][A-Za-z0-9_]*\})|%[A-Za-z_][A-Za-z0-9_]*%)$/i;

export type ModelProvider =
  | "openai_compatible"
  | "openai_responses"
  | "anthropic"
  | "gemini";

export interface ModelCurlImport {
  provider: ModelProvider;
  baseUrl: string;
  model: string | null;
  apiKey: string | null;
  insecureTls?: boolean;
  normalizations: Array<
    "url_scheme" | "json_indentation" | "json_line_continuation"
  >;
}

function invalid(message = INVALID_COMMAND): never {
  throw new Error(message);
}

function tokenize(command: string): string[] {
  if (!command.trim() || command.length > MAX_COMMAND_LENGTH) invalid();

  const tokens: string[] = [];
  let value = "";
  let started = false;
  let quote: "'" | '"' | null = null;
  const push = () => {
    if (started) tokens.push(value);
    value = "";
    started = false;
    if (tokens.length > 128) invalid();
  };

  for (let index = 0; index < command.length; index += 1) {
    const char = command[index]!;
    const next = command[index + 1];

    if (quote === "'") {
      if (char === "'") quote = null;
      else value += char;
      started = true;
      continue;
    }

    if (quote === '"') {
      if (char === '"') {
        quote = null;
        started = true;
      } else if (char === "\\") {
        if (next === undefined) invalid();
        if (next === "\n" || (next === "\r" && command[index + 2] === "\n")) {
          index += next === "\r" ? 2 : 1;
          continue;
        }
        if (next === "$" || next === "`" || next === '"' || next === "\\") {
          value += next;
          index += 1;
        } else {
          value += char + next;
          index += 1;
        }
        started = true;
      } else if (char === "$" && (next === "(" || next === "{")) {
        const bracedReference = /^\$\{[A-Za-z_][A-Za-z0-9_]*\}/.exec(
          command.slice(index),
        )?.[0];
        if (!bracedReference) {
          invalid(
            "Shell expansion is not supported; paste the resolved request values.",
          );
        }
        value += bracedReference;
        index += bracedReference.length - 1;
        started = true;
      } else if (char === "$" && next !== undefined) {
        const reference = /^\$[A-Za-z_][A-Za-z0-9_]*/.exec(
          command.slice(index),
        )?.[0];
        if (!reference) invalid();
        value += reference;
        index += reference.length - 1;
        started = true;
      } else if (char === "$") {
        value += char;
        started = true;
      } else if (char === "`") {
        invalid();
      } else {
        value += char;
        started = true;
      }
      continue;
    }

    if (/\s/.test(char)) {
      push();
    } else if (char === "'" || char === '"') {
      quote = char;
      started = true;
    } else if (char === "\\") {
      if (next === undefined) invalid();
      if (next === "\n" || (next === "\r" && command[index + 2] === "\n")) {
        index += next === "\r" ? 2 : 1;
      } else {
        value += next;
        started = true;
        index += 1;
      }
    } else if (char === "`") {
      if (next === "\n" || (next === "\r" && command[index + 2] === "\n")) {
        index += next === "\r" ? 2 : 1;
      } else {
        invalid();
      }
    } else if (char === "^") {
      // Windows cmd uses a caret immediately before CRLF/LF as a line continuation.
      // Do not treat arbitrary carets as shell syntax or silently execute them.
      if (next === "\n" || (next === "\r" && command[index + 2] === "\n")) {
        index += next === "\r" ? 2 : 1;
      } else {
        invalid();
      }
    } else if (/[|;&<>]/.test(char)) {
      invalid(
        "Shell operators are not supported. Paste one cURL command without pipes or redirection.",
      );
    } else if (
      char === "$" &&
      (next === "(" || next === "{" || /[A-Za-z_]/.test(next ?? ""))
    ) {
      invalid(
        "Shell expansion is not supported; paste the resolved request values.",
      );
    } else if (
      char.charCodeAt(0) < 32 &&
      char !== "\r" &&
      char !== "\n" &&
      char !== "\t"
    ) {
      invalid();
    } else {
      value += char;
      started = true;
    }
  }

  if (quote !== null)
    invalid(
      "A quoted cURL argument is not closed. Copy the full command and check its closing quotes.",
    );
  push();
  return tokens;
}

function addCredential(
  current: string | null,
  candidate: string,
): string | null {
  const value = candidate.trim();
  // cURL examples commonly use environment variables; never expand or store them.
  if (ENVIRONMENT_REFERENCE.test(value)) return current;
  if (/\$(?:[A-Za-z_]|\{)/.test(value)) invalid();
  if (
    !value ||
    value.length > 4096 ||
    /[\u0000-\u001f\u007f]/.test(value) ||
    (current !== null && current !== value)
  ) {
    invalid();
  }
  return value;
}

function validModelId(value: string | null): string | null {
  if (value === null) return null;
  const model = value.trim();
  if (!model) return null;
  if (ENVIRONMENT_REFERENCE.test(model)) return null;
  if (model.length > 200 || /[\u0000-\u001f\u007f]/.test(model)) invalid();
  return model;
}

export function parseModelCurl(command: string): ModelCurlImport {
  const tokens = tokenize(command);
  if (!/^curl(?:\.exe)?$/i.test(tokens.shift() ?? "")) invalid();

  const headers: Array<[string, string]> = [];
  let body: string | null = null;
  let urlText: string | null = null;
  let insecureTls = false;
  const normalizations: ModelCurlImport["normalizations"] = [];
  const readOptionValue = () => {
    const value = tokens[++index];
    if (value === undefined) invalid("A cURL option is missing a value.");
    return value;
  };
  let index = -1;

  while (++index < tokens.length) {
    const token = tokens[index]!;
    if (token === "-k" || token === "--insecure") {
      insecureTls = true;
      continue;
    }
    if (token === "--no-insecure") {
      insecureTls = false;
      continue;
    }
    if (
      token === "-K" ||
      token === "--config" ||
      token.startsWith("--config=")
    ) {
      invalid(
        "cURL config-file options are not supported; paste request fields directly.",
      );
    }
    if (/^-[sk]+$/.test(token)) {
      insecureTls ||= token.slice(1).includes("k");
      continue;
    }
    let option: string;
    let inlineValue: string | undefined;
    const equalsAt = token.indexOf("=");
    if (token.startsWith("--") && equalsAt > 0) {
      option = token.slice(0, equalsAt);
      inlineValue = token.slice(equalsAt + 1);
    } else {
      option = token;
    }

    if (["-H", "--header"].includes(option)) {
      const header = inlineValue ?? readOptionValue();
      const colon = header.indexOf(":");
      if (colon < 1) invalid();
      headers.push([
        header.slice(0, colon).trim().toLowerCase(),
        header.slice(colon + 1).trim(),
      ]);
    } else if (
      ["-d", "--data", "--data-raw", "--data-binary", "--json"].includes(option)
    ) {
      if (body !== null)
        invalid("Model import accepts a single inline JSON body.");
      body = inlineValue ?? readOptionValue();
    } else if (option === "--url") {
      if (urlText !== null) invalid();
      urlText = inlineValue ?? readOptionValue();
    } else if (option === "-X" || option === "--request") {
      if (!/^[A-Z]+$/i.test(inlineValue ?? readOptionValue())) invalid();
    } else if (
      [
        "-s",
        "-S",
        "-L",
        "--silent",
        "--show-error",
        "--location",
        "--compressed",
        "--fail",
        "--fail-with-body",
      ].includes(option) ||
      /^-[sSL]+$/.test(option)
    ) {
      continue;
    } else if (token.startsWith("-")) {
      const name = /^(?:--[A-Za-z][A-Za-z0-9-]{0,39}|-[A-Za-z])$/.test(option)
        ? ` ${option}`
        : "";
      invalid(
        `Unsupported cURL option${name}. Remove it or fill the connection fields manually.`,
      );
    } else if (urlText === null) {
      urlText = token;
    } else {
      invalid();
    }
  }

  if (!urlText) invalid("No endpoint URL was found in the cURL command.");
  // Some web consoles escape the scheme separator as ``https\://`` when
  // copying a command. Normalize only this presentation-only escape; the
  // resulting URL still passes the strict HTTP(S) checks below. Use explicit
  // prefix handling here so the backslash is not confused with regex syntax.
  for (const scheme of ["http", "https"] as const) {
    const escapedPrefix = `${scheme}\\://`;
    if (urlText.toLowerCase().startsWith(escapedPrefix)) {
      urlText = `${scheme}://${urlText.slice(escapedPrefix.length)}`;
      normalizations.push("url_scheme");
      break;
    }
  }
  let url: URL;
  try {
    url = new URL(urlText);
  } catch {
    return invalid(
      "The endpoint URL is invalid. Check the address or paste it into the Base URL field.",
    );
  }
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.username ||
    url.password ||
    url.hash ||
    /[\u0000-\u001f\u007f]/.test(urlText)
  )
    invalid();
  if (/\/v1\/chat-messages\/?$/i.test(url.pathname)) {
    invalid(DIFY_APP_COMMAND);
  }

  let apiKey: string | null = null;
  for (const [name, value] of headers) {
    if (name === "authorization" && value) {
      const bearer = /^Bearer\s+(.+)$/i.exec(value);
      if (!bearer) invalid();
      apiKey = addCredential(apiKey, bearer[1]!);
    } else if (
      ["x-api-key", "api-key", "x-goog-api-key"].includes(name) &&
      value
    ) {
      apiKey = addCredential(apiKey, value);
    }
  }

  for (const [name, value] of url.searchParams) {
    if (name === "key" || name === "api_key") {
      apiKey = addCredential(apiKey, value);
    } else {
      invalid();
    }
  }
  url.search = "";

  let bodyModel: string | null = null;
  if (body !== null) {
    try {
      JSON.parse(body);
    } catch {
      // Some clients copy pretty-printed JSON with shell-style backslash line
      // breaks inside a single-quoted argument. This parser never evaluates
      // the shell; normalize only that narrow JSON presentation artifact.
      const originalBody = body;
      const continued = body.replace(/\\[ \t]*(?:\r?\n)[ \t]*/g, "\n");
      const repaired = continued.replace(
        /^[ \t]*(?:&#(?:x20|32);[ \t]*)+/gim,
        " ",
      );
      if (repaired === body) {
        invalid(
          "The model request body is not valid inline JSON. Check its quoting or fill the model field manually.",
        );
      }
      try {
        JSON.parse(repaired);
        body = repaired;
        if (continued !== originalBody) {
          normalizations.push("json_line_continuation");
        }
        if (repaired !== continued) normalizations.push("json_indentation");
      } catch {
        invalid(
          "The model request body is not valid inline JSON. Check its quoting or fill the model field manually.",
        );
      }
    }
    try {
      const parsed: unknown = JSON.parse(body);
      if (
        parsed &&
        typeof parsed === "object" &&
        "model" in parsed &&
        typeof parsed.model === "string"
      ) {
        bodyModel = parsed.model.trim() || null;
      }
    } catch {
      invalid(
        "The model request body is not valid inline JSON. Check its quoting or fill the model field manually.",
      );
    }
  }

  const path = url.pathname.replace(/\/+$/, "");
  const gemini = /\/v1beta\/models\/([^/:]+)(?::[^/]+)?$/i.exec(path);
  const anthropic =
    /\/v1\/messages$/i.test(path) ||
    headers.some(([name]) => name === "anthropic-version");
  let provider: ModelProvider = "openai_compatible";
  let model = bodyModel;
  let basePath = path;

  if (gemini || headers.some(([name]) => name === "x-goog-api-key")) {
    provider = "gemini";
    if (gemini) {
      let pathModel: string;
      try {
        pathModel = decodeURIComponent(gemini[1]!);
      } catch {
        return invalid();
      }
      if (model && model !== pathModel) invalid();
      model = pathModel;
      basePath = path.slice(0, gemini.index).replace(/\/$/, "");
    } else {
      basePath = path.replace(/\/v1beta(?:\/.*)?$/i, "");
    }
  } else if (anthropic) {
    provider = "anthropic";
    basePath = path.replace(/\/v1\/messages$/i, "");
  } else if (/\/responses$/i.test(path)) {
    provider = "openai_responses";
    basePath = path.replace(/\/responses$/i, "");
  } else if (/\/chat\/completions$/i.test(path)) {
    basePath = path.replace(/\/chat\/completions$/i, "");
  } else if (/\/models$/i.test(path)) {
    basePath = path.replace(/\/models$/i, "");
  }

  const baseUrl = `${url.origin}${basePath}`.replace(/\/$/, "");
  if (baseUrl.length > 2048 || !baseUrl) invalid();
  return {
    provider,
    baseUrl,
    model: validModelId(model),
    apiKey,
    ...(insecureTls && url.protocol === "https:" ? { insecureTls: true } : {}),
    normalizations,
  };
}

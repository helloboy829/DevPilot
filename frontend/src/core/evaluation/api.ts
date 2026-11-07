import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export async function evaluationApi<T>(
  route: string,
  body?: unknown,
  method = "POST",
): Promise<T> {
  const response = await fetch(`${getBackendBaseURL()}/api/${route}`, {
    method: body === undefined && method === "POST" ? "GET" : method,
    cache: "no-store",
    headers:
      body === undefined ? undefined : { "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (!response.ok)
    await throwGatewayApiError(
      response,
      "Operation failed; check permissions and configuration",
    );
  return response.json() as Promise<T>;
}

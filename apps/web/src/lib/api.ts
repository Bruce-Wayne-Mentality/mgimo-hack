// Thin fetch wrapper: same-origin session cookie, CSRF header on changes,
// errors in the documented {"error": {code, message, fields}} format.

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly fields: Record<string, string>;
  readonly retryAfter: number | null;

  constructor(status: number, code: string, message: string, fields: Record<string, string> = {}, retryAfter: number | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.fields = fields;
    this.retryAfter = retryAfter;
  }
}

const SAFE = new Set(["GET", "HEAD", "OPTIONS"]);
const GENERIC = "Не удалось выполнить запрос. Попробуйте ещё раз.";

let csrfToken: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

type Options = {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
  /** Do not trigger the global "session ended" handler on 401. */
  quiet401?: boolean;
};

function errorFrom(status: number, data: unknown, retryAfter: string | null): ApiError {
  const retry = retryAfter ? Number.parseInt(retryAfter, 10) : null;
  if (data && typeof data === "object") {
    const record = data as Record<string, unknown>;
    const error = record.error as { code?: string; message?: string; fields?: Record<string, string> } | undefined;
    if (error && typeof error.message === "string") {
      return new ApiError(status, error.code ?? "error", error.message, error.fields ?? {}, retry);
    }
    if (typeof record.detail === "string") return new ApiError(status, "error", record.detail, {}, retry);
  }
  if (status >= 500) return new ApiError(status, "server_error", "Сервис временно недоступен. Попробуйте позже.");
  return new ApiError(status, "error", GENERIC, {}, retry);
}

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (!SAFE.has(method) && csrfToken) headers["X-CSRF-Token"] = csrfToken;

  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      credentials: "same-origin",
      cache: "no-store",
      signal: options.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, "network", "Нет связи с сервером. Проверьте интернет и повторите.");
  }

  const isJson = response.headers.get("content-type")?.includes("application/json");
  const data: unknown = response.status === 204 || !isJson ? null : await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401 && !options.quiet401) onUnauthorized?.();
    throw errorFrom(response.status, data, response.headers.get("Retry-After"));
  }
  return data as T;
}

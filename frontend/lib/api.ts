const RAW_API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
/** "same-origin": API served from the same host (remote access through Cloudflare). */
export const SAME_ORIGIN = RAW_API_URL === "same-origin";
export const API_URL = SAME_ORIGIN ? "" : RAW_API_URL.replace(/\/$/, "");

export class ApiError extends Error {
  status: number;
  code?: string;
  constructor(status: number, message: string, code?: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export async function api<T = any>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init || {};
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...rest,
      credentials: SAME_ORIGIN ? "same-origin" : "omit",
      headers: { ...(json !== undefined ? { "Content-Type": "application/json" } : {}), ...(rest.headers || {}) },
      body: json !== undefined ? JSON.stringify(json) : rest.body,
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, `Cannot reach the MarketPilot backend at ${API_URL || "this server"}. Is it running? (python -m marketpilot)`);
  }
  const text = await res.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (res.status === 401 && typeof window !== "undefined") window.dispatchEvent(new Event("mp-auth-required"));
  if (!res.ok) {
    const detail = typeof data?.detail === "string" ? data.detail : JSON.stringify(data?.detail ?? data);
    throw new ApiError(res.status, detail || res.statusText, data?.code);
  }
  return data as T;
}

export const post = <T = any>(path: string, json?: unknown) => api<T>(path, { method: "POST", json: json ?? {} });
export const put = <T = any>(path: string, json?: unknown) => api<T>(path, { method: "PUT", json: json ?? {} });
export const del = <T = any>(path: string) => api<T>(path, { method: "DELETE" });

export function wsUrl(): string {
  if (SAME_ORIGIN) {
    const { protocol, host } = window.location;
    return `${protocol === "https:" ? "wss" : "ws"}://${host}/api/ws`;
  }
  return API_URL.replace(/^http/, "ws") + "/api/ws";
}

// Empty string (production behind Caddy) = same origin, so the app also works on each company's own domain.
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Two independent sessions: the company user ("token") and the platform admin ("ptoken").
// While the admin is inside a company, both exist and the company token is an impersonation token.
const read = (k: string) => { try { return typeof window === "undefined" ? null : localStorage.getItem(k); } catch { return null; } };
const write = (k: string, v: string | null) => { try { if (v) localStorage.setItem(k, v); else localStorage.removeItem(k); } catch {} };

export const getToken = () => read("token");
export const setToken = (t: string | null) => write("token", t);
export const getPlatformToken = () => read("ptoken");
export const setPlatformToken = (t: string | null) => write("ptoken", t);

export class ApiError extends Error { constructor(public status: number, message: string) { super(message); } }

type Init = RequestInit & { json?: unknown; platform?: boolean };

async function errorFrom(res: Response): Promise<ApiError> {
  let detail: unknown = res.statusText;
  try { detail = (await res.json()).detail ?? detail; } catch {}
  if (Array.isArray(detail)) detail = detail.map((d: any) => `${(d.loc ?? []).slice(-1)[0] ?? ""}: ${d.msg}`).join("\n");
  return new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
}

export async function api<T = any>(path: string, init: Init = {}): Promise<T> {
  const { json, platform, ...rest } = init;
  const headers: Record<string, string> = { ...(rest.headers as Record<string, string>) };
  const token = platform ? getPlatformToken() : getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let body = rest.body;
  if (json !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(json); }
  const res = await fetch(`${API_URL}${path}`, { ...rest, headers, body });
  if (res.status === 401 && typeof window !== "undefined") {
    if (platform) setPlatformToken(null); else setToken(null);
    window.location.href = "/login";
  }
  if (!res.ok) throw await errorFrom(res);
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const logoUrl = (companyId: number, version?: string | null) => `${API_URL}/api/public/logo/${companyId}${version ? `?v=${encodeURIComponent(version)}` : ""}`;

/** GET a paginated list: returns the rows and the total from the X-Total-Count header. */
export async function apiPage<T = any>(path: string, opts: { platform?: boolean } = {}): Promise<{ rows: T[]; total: number }> {
  const token = opts.platform ? getPlatformToken() : getToken();
  const res = await fetch(`${API_URL}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (res.status === 401 && typeof window !== "undefined") { if (opts.platform) setPlatformToken(null); else setToken(null); window.location.href = "/login"; }
  if (!res.ok) throw await errorFrom(res);
  const rows = await res.json();
  return { rows, total: Number(res.headers.get("X-Total-Count") ?? rows.length) };
}

/** Multipart upload (Excel import, documents, logo). */
export async function upload<T = any>(path: string, file: File, fields: Record<string, string> = {}): Promise<T> {
  const fd = new FormData();
  fd.append("file", file);
  for (const [k, v] of Object.entries(fields)) fd.append(k, v);
  const res = await fetch(`${API_URL}${path}`, { method: "POST", body: fd, headers: { Authorization: `Bearer ${getToken()}` } });
  if (!res.ok) throw await errorFrom(res);
  return res.json();
}

/** Download an authenticated file (Excel templates / exports) and save it. */
export async function download(path: string, fallbackName = "export.xlsx", opts: { platform?: boolean } = {}) {
  const res = await fetch(`${API_URL}${path}`, { headers: { Authorization: `Bearer ${opts.platform ? getPlatformToken() : getToken()}` } });
  if (!res.ok) throw await errorFrom(res);
  const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "")?.[1] ?? fallbackName;
  const url = URL.createObjectURL(await res.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function login(email: string, password: string, otp?: string): Promise<"company" | "platform"> {
  const form = new URLSearchParams({ username: email, password });
  if (otp) form.set("otp", otp);
  const res = await fetch(`${API_URL}/api/auth/login`, { method: "POST", body: form });
  if (!res.ok) throw await errorFrom(res);
  const data = await res.json();
  if (data.kind === "platform") { setPlatformToken(data.access_token); setToken(null); return "platform"; }
  setToken(data.access_token);
  return "company";
}

export function logout() { setToken(null); setPlatformToken(null); write("session:cache", null); }

const base = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");
export async function request<T>(path: string, token: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(base + path, { method: body === undefined ? "GET" : "POST", signal,
    headers: { Accept: "application/json", Authorization: `Bearer ${token}`,
      ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(typeof error.detail === "string" ? error.detail : error.message ?? `请求失败 (${response.status})`);
  }
  return response.json() as Promise<T>;
}
export async function download(path: string, token: string) {
  const response = await fetch(base + path, { headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) throw new Error(`文档下载失败 (${response.status})`);
  save(await response.text());
}
export function save(text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
  const link = document.createElement("a"); link.href = url; link.download = "interfaces.md"; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function socketUrl(path: string, token: string) {
  const url = new URL(base || location.origin); url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = path; url.search = new URLSearchParams({ token }).toString(); return url.href;
}

import type { ChatMessage, CouponsData, Deal, HistoryData, PlatformStatus, ProductsData } from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

export function wsUrl(sessionId: string): string {
  const base = process.env.NEXT_PUBLIC_WS_URL || API_URL.replace(/^http/, "ws");
  return `${base.replace(/\/$/, "")}/ws/chat/${encodeURIComponent(sessionId)}`;
}

async function get<T>(path: string, params?: Record<string, string | number | undefined | null>): Promise<T> {
  const url = new URL(API_URL + path);
  Object.entries(params ?? {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, String(v));
  });
  const res = await fetch(url.toString(), { cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export const api = {
  search: (q: string, opts: { category?: string; budget_max?: number; platforms?: string } = {}) =>
    get<ProductsData>("/api/products/search", { q, ...opts }),
  product: (id: number) => get<Record<string, unknown>>(`/api/products/${id}`),
  history: (id: number, months = 12) => get<HistoryData>(`/api/history/${id}`, { months }),
  coupons: (opts: { platform?: string; bank?: string; price?: number } = {}) =>
    get<Deal[]>("/api/coupons", opts).then((items): CouponsData => ({
      platform: opts.platform ?? null,
      bank_name: opts.bank ?? null,
      price: opts.price ?? null,
      items,
    })),
  platforms: () => get<PlatformStatus[]>("/api/platforms"),
  chatHistory: (sessionId: string) =>
    get<{ role: "user" | "assistant"; content: string; blocks?: ChatMessage["blocks"] }[]>(
      `/api/chat/${encodeURIComponent(sessionId)}/history`,
    ),
};

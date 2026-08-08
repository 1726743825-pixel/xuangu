const API_BASE = (process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000").replace(/\/$/, "");

type ApiEnvelope<T> = { code?: number; data?: T; message?: string };

export function apiUrl(path: string) {
  return `${API_BASE}${path}`;
}

export async function fetcher<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`请求失败（${response.status}）`);
  }

  const payload = (await response.json()) as T | ApiEnvelope<T>;
  if (payload && typeof payload === "object" && "data" in payload && payload.data !== undefined) {
    return payload.data;
  }
  return payload as T;
}

export function getLatestTradingDate() {
  const chinaNow = new Date(Date.now() + 8 * 60 * 60 * 1000);
  const candidate = new Date(
    Date.UTC(chinaNow.getUTCFullYear(), chinaNow.getUTCMonth(), chinaNow.getUTCDate()),
  );

  // 当日收盘前默认查看上一个完整交易日。
  if (chinaNow.getUTCHours() < 15) candidate.setUTCDate(candidate.getUTCDate() - 1);
  while (candidate.getUTCDay() === 0 || candidate.getUTCDay() === 6) {
    candidate.setUTCDate(candidate.getUTCDate() - 1);
  }
  return candidate.toISOString().slice(0, 10);
}

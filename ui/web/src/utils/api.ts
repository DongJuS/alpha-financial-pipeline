/**
 * ui/src/utils/api.ts — Axios 인스턴스 및 공통 API 유틸
 */
import axios from "axios";

export const api = axios.create({
  baseURL: "/api/v1",
  timeout: 10_000,
  headers: { "Content-Type": "application/json" },
});

// 요청 인터셉터: JWT 토큰 자동 주입
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("alpha_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// 응답 인터셉터: 401 처리 (세션 만료 감지 → /login?expired=true 리다이렉트)
api.interceptors.response.use(
  (res) => res,
  (err) => {
    const requestUrl = String(err.config?.url ?? "");
    const isLoginRequest = requestUrl.includes("/auth/login");
    if (err.response?.status === 401 && !isLoginRequest) {
      localStorage.removeItem("alpha_token");
      window.location.href = "/login?expired=true";
    }
    return Promise.reject(err);
  }
);

/** 금액 포맷 (₩1,234,567) */
export function formatKRW(value: number): string {
  return `₩${value.toLocaleString("ko-KR")}`;
}

/** 수익률 포맷 (+1.39% / -0.52%) */
export function formatPct(value: number): string {
  const sign = value >= 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

/** MDD 포맷 (0.00% / -1.39%) — MDD는 항상 0 이하 */
export function formatMDD(value: number): string {
  if (value === 0) return "0.00%";
  return `-${Math.abs(value).toFixed(2)}%`;
}

/** 시그널 배지 클래스 */
export function signalBadgeClass(signal: string): string {
  if (signal === "BUY") return "badge-buy";
  if (signal === "SELL") return "badge-sell";
  return "badge-hold";
}

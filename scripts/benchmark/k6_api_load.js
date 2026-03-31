/**
 * k6_api_load.js — FastAPI 부하 테스트
 *
 * 실행:
 *   k6 run scripts/benchmark/k6_api_load.js
 *   k6 run --out json=scripts/benchmark/results/k6_result.json scripts/benchmark/k6_api_load.js
 *
 * 환경변수:
 *   API_BASE_URL  (default: http://localhost:18000)
 *   API_EMAIL     (default: admin@alpha-trading.com)
 *   API_PASSWORD  (default: admin)
 */

import http from "k6/http";
import { check, group, sleep } from "k6";
import { Rate, Trend } from "k6/metrics";

// ── 커스텀 메트릭 ───────────────────────────────────────────────
const errorRate = new Rate("error_rate");
const healthLatency = new Trend("health_latency", true);
const positionsLatency = new Trend("positions_latency", true);
const tickersLatency = new Trend("tickers_latency", true);
const marketplaceLatency = new Trend("marketplace_latency", true);

// ── 설정 ─────────────────────────────────────────────────────────
const BASE_URL = __ENV.API_BASE_URL || "http://localhost:18000";
const EMAIL = __ENV.API_EMAIL || "admin@alpha-trading.com";
const PASSWORD = __ENV.API_PASSWORD || "admin";

export const options = {
  scenarios: {
    // 시나리오 1: 워밍업 — 10 동시 사용자, 30초
    warmup: {
      executor: "constant-vus",
      vus: 10,
      duration: "30s",
      startTime: "0s",
      tags: { scenario: "warmup_10vu" },
    },
    // 시나리오 2: 중간 부하 — 50 동시 사용자, 30초
    medium: {
      executor: "constant-vus",
      vus: 50,
      duration: "30s",
      startTime: "35s",
      tags: { scenario: "medium_50vu" },
    },
    // 시나리오 3: 고부하 — 100 동시 사용자, 30초
    heavy: {
      executor: "constant-vus",
      vus: 100,
      duration: "30s",
      startTime: "70s",
      tags: { scenario: "heavy_100vu" },
    },
  },
  thresholds: {
    http_req_duration: ["p(95)<2000"], // p95 < 2초
    error_rate: ["rate<0.1"],          // 에러율 < 10%
  },
};

// ── Setup: JWT 토큰 발급 ────────────────────────────────────────
export function setup() {
  const loginRes = http.post(
    `${BASE_URL}/api/v1/auth/login`,
    JSON.stringify({ email: EMAIL, password: PASSWORD }),
    { headers: { "Content-Type": "application/json" } }
  );

  const success = check(loginRes, {
    "login status 200": (r) => r.status === 200,
    "login has token": (r) => {
      try {
        return JSON.parse(r.body).token !== undefined;
      } catch {
        return false;
      }
    },
  });

  if (!success) {
    console.error(`Login failed: ${loginRes.status} ${loginRes.body}`);
    // 토큰 없이도 /health 테스트는 가능하도록 빈 토큰 반환
    return { token: "" };
  }

  const token = JSON.parse(loginRes.body).token;
  console.log("JWT token acquired successfully");
  return { token };
}

// ── 메인 VU 시나리오 ────────────────────────────────────────────
export default function (data) {
  const authHeaders = {
    headers: {
      Authorization: `Bearer ${data.token}`,
      "Content-Type": "application/json",
    },
  };
  const noAuthHeaders = {
    headers: { "Content-Type": "application/json" },
  };

  // ── 1. /health (인증 불필요) ──────────────────────────────────
  group("health_check", () => {
    const res = http.get(`${BASE_URL}/health`, noAuthHeaders);
    const ok = check(res, {
      "health: status 200": (r) => r.status === 200,
    });
    errorRate.add(!ok);
    healthLatency.add(res.timings.duration);
  });

  sleep(0.1);

  // ── 2. /api/v1/portfolio/positions (인증 필요) ────────────────
  group("portfolio_positions", () => {
    const res = http.get(
      `${BASE_URL}/api/v1/portfolio/positions`,
      authHeaders
    );
    const ok = check(res, {
      "positions: status 2xx": (r) => r.status >= 200 && r.status < 300,
    });
    errorRate.add(!ok);
    positionsLatency.add(res.timings.duration);
  });

  sleep(0.1);

  // ── 3. /api/v1/market/tickers (인증 필요) ─────────────────────
  group("market_tickers", () => {
    const res = http.get(
      `${BASE_URL}/api/v1/market/tickers`,
      authHeaders
    );
    const ok = check(res, {
      "tickers: status 2xx": (r) => r.status >= 200 && r.status < 300,
    });
    errorRate.add(!ok);
    tickersLatency.add(res.timings.duration);
  });

  sleep(0.1);

  // ── 4. /api/v1/marketplace/stocks (인증 필요) ─────────────────
  group("marketplace_stocks", () => {
    const res = http.get(
      `${BASE_URL}/api/v1/marketplace/stocks?limit=20`,
      authHeaders
    );
    const ok = check(res, {
      "marketplace: status 2xx": (r) => r.status >= 200 && r.status < 300,
    });
    errorRate.add(!ok);
    marketplaceLatency.add(res.timings.duration);
  });

  sleep(0.1);

  // ── 5. /api/v1/system/overview (인증 필요) ────────────────────
  group("system_overview", () => {
    const res = http.get(
      `${BASE_URL}/api/v1/system/overview`,
      authHeaders
    );
    check(res, {
      "system: status 2xx": (r) => r.status >= 200 && r.status < 300,
    });
  });

  sleep(0.3);
}

// ── Teardown: 요약 출력 ─────────────────────────────────────────
export function teardown(data) {
  console.log("=".repeat(64));
  console.log("  k6 부하 테스트 완료");
  console.log("=".repeat(64));
}

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import Portfolio from "@/pages/Portfolio";

vi.mock("recharts", () => {
  const passthrough = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;
  return {
    ResponsiveContainer: passthrough,
    LineChart: passthrough,
    CartesianGrid: () => null,
    Line: () => null,
    Tooltip: () => null,
    XAxis: () => null,
    YAxis: () => null,
  };
});

vi.mock("@/hooks/usePortfolio", () => ({
  usePortfolio: () => ({
    data: {
      total_value: 6_728_200,
      total_pnl: 14_865,
      total_pnl_pct: 0.22,
      is_paper: true,
      positions: [],
    },
    isLoading: false,
  }),
  useTradingAccountOverview: () => ({
    data: {
      account_scope: "paper",
      broker_name: "한국투자증권 KIS",
      account_label: "KIS 모의투자 계좌",
      base_currency: "KRW",
      seed_capital: 10_000_000,
      cash_balance: 3_286_470,
      buying_power: 3_286_470,
      position_market_value: 6_728_200,
      total_equity: 10_014_670,
      realized_pnl: 0,
      unrealized_pnl: 14_865,
      total_pnl: 14_865,
      total_pnl_pct: 0.15,
      position_count: 4,
      last_snapshot_at: "2026-03-13T14:39:18.258524Z",
    },
    isLoading: false,
  }),
  usePerformance: () => ({
    data: {
      period: "monthly",
      return_pct: 0,
      max_drawdown_pct: 0,
      sharpe_ratio: null,
      win_rate: 0,
      total_trades: 44,
      kospi_benchmark_pct: 0.08,
    },
    isLoading: false,
  }),
  usePerformanceSeries: () => ({
    data: { points: [] },
    isLoading: false,
  }),
  useTradeHistory: () => ({
    data: { data: [], meta: { page: 1, per_page: 30 } },
    isLoading: false,
  }),
}));

vi.mock("@/utils/api", () => ({
  formatKRW: (value: number) => `₩${value.toLocaleString("ko-KR")}`,
  formatPct: (value: number) => `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`,
}));

describe("Portfolio page", () => {
  it("uses account overview totals in the hero summary", () => {
    render(<Portfolio />);

    expect(screen.getByText("총 자산 ₩10,014,670")).toBeInTheDocument();
    expect(screen.getByText("누적 손익 ₩14,865")).toBeInTheDocument();
    expect(screen.getByText("페이퍼 트레이딩")).toBeInTheDocument();
  });
});

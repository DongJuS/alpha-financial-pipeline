import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import Dashboard from "@/pages/Dashboard";

vi.mock("@/hooks/useAgentStatus", () => ({
  useAgentStatus: () => ({ data: [], isLoading: false }),
}));

vi.mock("@/hooks/usePortfolio", () => ({
  usePortfolio: () => ({
    data: {
      total_value: 6_728_200,
      total_pnl: 14_865,
      total_pnl_pct: 0.22,
      is_paper: true,
      positions: [
        {
          ticker: "034020",
          name: "두산에너빌리티",
          quantity: 16,
          avg_price: 107_985,
          current_price: 108_630,
          unrealized_pnl: 10_320,
          weight_pct: 25.83,
        },
      ],
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
  usePortfolioConfig: () => ({
    data: {
      strategy_blend_ratio: 0.5,
      max_position_pct: 20,
      daily_loss_limit_pct: 3,
      is_paper_trading: true,
      enable_paper_trading: true,
      enable_real_trading: false,
      primary_account_scope: "paper",
      market_hours_enforced: true,
      market_status: "after_hours",
    },
    isLoading: false,
  }),
  usePerformance: () => ({ data: null, isLoading: false }),
  usePerformanceSeries: () => ({ data: { points: [] }, isLoading: false }),
}));

vi.mock("@/utils/api", () => ({
  api: { get: vi.fn() },
  formatPct: (value: number) => `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`,
}));

describe("Dashboard page", () => {
  it("shows account-level totals from trading account overview", () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <Dashboard />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByText("10,014,670원")).toBeInTheDocument();
    expect(screen.getByText("+0.15%")).toBeInTheDocument();
    expect(screen.queryByText("6,728,200원")).not.toBeInTheDocument();
  });
});

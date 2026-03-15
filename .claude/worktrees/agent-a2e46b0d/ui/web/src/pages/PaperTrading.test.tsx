import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import PaperTrading from "@/pages/PaperTrading";

vi.mock("recharts", () => {
  const passthrough = ({ children }: { children?: ReactNode }) => <div>{children}</div>;
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
  usePaperTradingOverview: () => ({
    data: {
      broker: "한국투자증권 KIS",
      account_label: "KIS 모의투자 계좌",
      current_mode_is_paper: true,
      active_days_120d: 18,
      trade_count_120d: 42,
      traded_tickers_120d: 8,
      last_executed_at: "2026-03-13T15:20:00+09:00",
      latest_run: {
        scenario: "baseline",
        simulated_days: 120,
        trade_count: 42,
        return_pct: 5.4,
        benchmark_return_pct: 1.2,
        max_drawdown_pct: -3.1,
        sharpe_ratio: 1.12,
        passed: true,
        summary: "baseline run",
        created_at: "2026-03-13T00:00:00+09:00",
      },
    },
    isLoading: false,
  }),
  useTradingAccountOverview: () => ({
    data: {
      account_scope: "paper",
      broker_name: "한국투자증권 KIS",
      account_label: "KIS 모의투자 계좌",
      base_currency: "KRW",
      seed_capital: 10000000,
      cash_balance: 9600000,
      buying_power: 9450000,
      position_market_value: 550000,
      total_equity: 10150000,
      realized_pnl: 50000,
      unrealized_pnl: 100000,
      total_pnl: 150000,
      total_pnl_pct: 1.5,
      position_count: 3,
      last_snapshot_at: "2026-03-13T15:25:00+09:00",
    },
    isLoading: false,
  }),
  useAccountSnapshots: () => ({
    data: {
      account_scope: "paper",
      points: [
        {
          account_scope: "paper",
          cash_balance: 9700000,
          buying_power: 9700000,
          position_market_value: 200000,
          total_equity: 9900000,
          realized_pnl: 0,
          unrealized_pnl: 0,
          position_count: 1,
          snapshot_source: "broker",
          snapshot_at: "2026-03-12T15:25:00+09:00",
        },
      ],
    },
    isLoading: false,
  }),
  useBrokerOrders: () => ({
    data: {
      account_scope: "paper",
      data: [
        {
          client_order_id: "paper-1",
          account_scope: "paper",
          broker_name: "internal-paper",
          ticker: "005930",
          name: "삼성전자",
          side: "BUY",
          order_type: "MARKET",
          requested_quantity: 2,
          requested_price: 71000,
          filled_quantity: 2,
          avg_fill_price: 71000,
          status: "FILLED",
          signal_source: "A",
          agent_id: "portfolio_manager_agent",
          broker_order_id: "paper-1",
          rejection_reason: null,
          requested_at: "2026-03-13T09:00:00+09:00",
          filled_at: "2026-03-13T09:00:02+09:00",
        },
      ],
    },
    isLoading: false,
  }),
  usePortfolio: () => ({
    data: {
      total_value: 550000,
      total_pnl: 100000,
      total_pnl_pct: 2.0,
      is_paper: true,
      positions: [
        {
          ticker: "005930",
          name: "삼성전자",
          quantity: 2,
          avg_price: 70000,
          current_price: 71000,
          unrealized_pnl: 2000,
          weight_pct: 55.0,
        },
      ],
    },
    isLoading: false,
  }),
  usePerformance: () => ({
    data: {
      period: "monthly",
      return_pct: 5.4,
      max_drawdown_pct: -3.1,
      sharpe_ratio: 1.12,
      win_rate: 68.5,
      total_trades: 42,
      kospi_benchmark_pct: 1.2,
    },
    isLoading: false,
  }),
  usePerformanceSeries: () => ({
    data: {
      period: "monthly",
      points: [
        {
          date: "2026-03-10",
          portfolio_return_pct: 2.5,
          benchmark_return_pct: 1.1,
          realized_pnl_cum: 20000,
          trade_count: 10,
        },
      ],
    },
    isLoading: false,
  }),
  useTradeHistory: () => ({
    data: {
      data: [
        {
          ticker: "005930",
          name: "삼성전자",
          side: "BUY",
          quantity: 2,
          price: 71000,
          amount: 142000,
          signal_source: "A",
          agent_id: "portfolio_manager_agent",
          is_paper: true,
          circuit_breaker: false,
          executed_at: "2026-03-13T09:00:02+09:00",
        },
      ],
      meta: { page: 1, per_page: 50 },
    },
    isLoading: false,
  }),
}));

describe("PaperTrading page", () => {
  it("renders account summary and broker order sections", () => {
    render(<PaperTrading />);

    expect(screen.getAllByText("주문 가능 금액").length).toBeGreaterThan(0);
    expect(screen.getByText("계좌 자산 흐름")).toBeInTheDocument();
    expect(screen.getByText("주문 요청 및 체결")).toBeInTheDocument();
    expect(screen.getAllByText("체결 완료").length).toBeGreaterThan(0);
    expect(screen.getAllByText("₩10,150,000").length).toBeGreaterThan(0);
  });
});

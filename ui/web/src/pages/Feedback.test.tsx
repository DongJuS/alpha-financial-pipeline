import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import Feedback from "@/pages/Feedback";

vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: any) => <div>{children}</div>,
  BarChart: ({ children }: any) => <div>{children}</div>,
  Bar: () => null,
  Cell: () => null,
  XAxis: () => null,
  YAxis: () => null,
  CartesianGrid: () => null,
  Tooltip: () => null,
}));

vi.mock("@/hooks/useFeedback", () => ({
  useAccuracy: () => ({
    data: [
      {
        strategy: "A",
        accuracy: 0.65,
        total_predictions: 100,
        correct_predictions: 65,
        evaluated_predictions: 100,
        signal_distribution: { BUY: 0.4, SELL: 0.3, HOLD: 0.3 },
        period_start: "2026-02-14",
        period_end: "2026-03-14",
      },
      {
        strategy: "B",
        accuracy: 0.58,
        total_predictions: 80,
        correct_predictions: 46,
        evaluated_predictions: 80,
        signal_distribution: { BUY: 0.35, SELL: 0.35, HOLD: 0.3 },
        period_start: "2026-02-14",
        period_end: "2026-03-14",
      },
    ],
    isLoading: false,
  }),
  useLLMContext: () => ({ data: null, isLoading: false }),
  useRunBacktest: () => ({ mutate: vi.fn(), isPending: false, data: null }),
  useCompareStrategies: () => ({ mutate: vi.fn(), isPending: false, data: null }),
  useRetrainTicker: () => ({ mutate: vi.fn(), isPending: false, data: null }),
  useRetrainAll: () => ({ mutate: vi.fn(), isPending: false, data: null }),
  useRunFeedbackCycle: () => ({ mutate: vi.fn(), isPending: false, data: null }),
}));

vi.mock("@/utils/api", () => ({
  api: { get: vi.fn() },
  formatPct: (value: number) => `${value >= 0 ? "+" : ""}${(value * 100).toFixed(2)}%`,
}));

describe("Feedback page", () => {
  it("renders hero section with feedback title", () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <Feedback />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByText("성과 분석")).toBeInTheDocument();
  });

  it("shows accuracy KPI cards for strategies", () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <Feedback />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByText("전략 A")).toBeInTheDocument();
    expect(screen.getByText("65.0%")).toBeInTheDocument();
  });

  it("shows tab navigation", () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <Feedback />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByText("예측 정확도")).toBeInTheDocument();
    expect(screen.getByText("백테스트")).toBeInTheDocument();
    expect(screen.getByText("LLM 피드백")).toBeInTheDocument();
    expect(screen.getByText("피드백 사이클")).toBeInTheDocument();
  });

  it("shows signal distribution table", () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <Feedback />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByText("BUY")).toBeInTheDocument();
    expect(screen.getByText("SELL")).toBeInTheDocument();
    expect(screen.getByText("HOLD")).toBeInTheDocument();
  });
});

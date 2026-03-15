import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import RLTrading from "@/pages/RLTrading";

vi.mock("@/hooks/useRL", () => ({
  usePolicies: () => ({
    data: [
      {
        id: 1,
        ticker: "005930",
        version: "v1.0",
        algorithm: "TabularQ",
        mode: "shadow",
        excess_return: 0.052,
        sharpe_ratio: 1.23,
        win_rate: 0.58,
        walk_forward_passed: true,
        is_active: true,
      },
    ],
    isLoading: false,
  }),
  useActivePolicies: () => ({ data: [{ id: 1 }], isLoading: false }),
  useExperiments: () => ({ data: [], isLoading: false }),
  useEvaluations: () => ({ data: [], isLoading: false }),
  useShadowPolicies: () => ({ data: [], isLoading: false }),
  useShadowPerformance: () => ({ data: null, isLoading: false }),
  useActivatePolicy: () => ({ mutate: vi.fn() }),
  useCreateTrainingJob: () => ({ mutate: vi.fn(), isPending: false, isSuccess: false, data: null }),
  useRunWalkForward: () => ({ mutate: vi.fn(), isPending: false, data: null }),
  usePromoteShadowToPaper: () => ({ mutate: vi.fn(), isPending: false, data: null }),
  usePromotePaperToReal: () => ({ mutate: vi.fn(), isPending: false, data: null }),
  usePolicyMode: () => ({ data: null, isLoading: false }),
}));

vi.mock("@/utils/api", () => ({
  api: { get: vi.fn() },
  formatPct: (value: number) => `${value >= 0 ? "+" : ""}${(value * 100).toFixed(2)}%`,
}));

describe("RLTrading page", () => {
  it("renders hero section with RL Trading title", () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <RLTrading />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByText("RL Trading")).toBeInTheDocument();
  });

  it("shows policy table with mock data", () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <RLTrading />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByText("005930")).toBeInTheDocument();
    expect(screen.getByText("TabularQ")).toBeInTheDocument();
  });

  it("shows active policies count", () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <RLTrading />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByText("1")).toBeInTheDocument();
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
          <RLTrading />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByText("정책 관리")).toBeInTheDocument();
    expect(screen.getByText("학습 실험")).toBeInTheDocument();
    expect(screen.getByText("섀도우 추론")).toBeInTheDocument();
    expect(screen.getByText("승격 게이트")).toBeInTheDocument();
  });
});

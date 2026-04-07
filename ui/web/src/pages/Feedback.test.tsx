import type { ReactNode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Feedback from "@/pages/Feedback";
import type { BanditSnapshot, RetrainResultItem } from "@/hooks/useFeedback";

vi.mock("recharts", () => {
  const passthrough = ({ children }: { children?: ReactNode }) => <div>{children}</div>;
  return {
    ResponsiveContainer: passthrough,
    BarChart: passthrough,
    Bar: () => null,
    Cell: () => null,
    CartesianGrid: () => null,
    Tooltip: () => null,
    XAxis: () => null,
    YAxis: () => null,
  };
});

const retrainTickerMutate = vi.fn();
const retrainAllMutate = vi.fn();
const runCycleMutate = vi.fn();

let retrainTickerState: {
  data: RetrainResultItem | null;
  isPending: boolean;
  mutate: typeof retrainTickerMutate;
} = {
  data: null,
  isPending: false,
  mutate: retrainTickerMutate,
};

let retrainAllState: {
  data: { total_tickers: number; successful: number; failed: number; results: RetrainResultItem[] } | null;
  isPending: boolean;
  mutate: typeof retrainAllMutate;
} = {
  data: null,
  isPending: false,
  mutate: retrainAllMutate,
};

vi.mock("@/hooks/useFeedback", () => ({
  useAccuracy: () => ({ data: [], isLoading: false }),
  useLLMContext: () => ({ data: null, isLoading: false }),
  useRunBacktest: () => ({ data: null, isPending: false, mutate: vi.fn() }),
  useCompareStrategies: () => ({ data: null, isPending: false, mutate: vi.fn() }),
  useRetrainTicker: () => retrainTickerState,
  useRetrainAll: () => retrainAllState,
  useRunFeedbackCycle: () => ({ data: null, isPending: false, mutate: runCycleMutate }),
}));

vi.mock("@/utils/api", () => ({
  api: { get: vi.fn(), post: vi.fn() },
  formatPct: (value: number) => `${value >= 0 ? "+" : ""}${(value * 100).toFixed(2)}%`,
}));

function makeSnapshot(overrides: Partial<BanditSnapshot> = {}): BanditSnapshot {
  return {
    ticker: "005930.KS",
    profile_id: "tabular_q_v2_momentum",
    epsilon: 0.2,
    ratios: [0.5, 0.6, 0.7, 0.8],
    best_ratio: 0.6,
    updated_at: "2026-04-07T13:51:00+00:00",
    arms: {
      "0.50": { ratio: 0.5, pulls: 2, total_reward: 1.2, mean_reward: 0.6, last_reward: 0.55, last_pulled_at: null },
      "0.60": { ratio: 0.6, pulls: 3, total_reward: 2.1, mean_reward: 0.7, last_reward: 0.72, last_pulled_at: null },
      "0.70": { ratio: 0.7, pulls: 1, total_reward: 0.4, mean_reward: 0.4, last_reward: 0.4, last_pulled_at: null },
      "0.80": { ratio: 0.8, pulls: 1, total_reward: 0.3, mean_reward: 0.3, last_reward: 0.3, last_pulled_at: null },
    },
    ...overrides,
  };
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Feedback />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function openCycleTab() {
  fireEvent.click(screen.getByRole("button", { name: /피드백 사이클/ }));
  await waitFor(() => {
    expect(screen.getByText("RL 개별 종목 재학습")).toBeInTheDocument();
  });
}

beforeEach(() => {
  retrainTickerMutate.mockReset();
  retrainAllMutate.mockReset();
  runCycleMutate.mockReset();
  retrainTickerState = { data: null, isPending: false, mutate: retrainTickerMutate };
  retrainAllState = { data: null, isPending: false, mutate: retrainAllMutate };
});

describe("Feedback page — RL bandit display", () => {
  it("renders selected_train_ratio badge after successful retrain", async () => {
    retrainTickerState = {
      data: {
        ticker: "005930",
        success: true,
        new_policy_id: 42,
        excess_return: 0.012,
        walk_forward_passed: true,
        deployed: true,
        error: null,
        selected_train_ratio: 0.6,
        bandit_snapshot: null,
      },
      isPending: false,
      mutate: retrainTickerMutate,
    };

    renderPage();
    await openCycleTab();

    expect(screen.getByText(/선택된 학습 비율/)).toBeInTheDocument();
    expect(screen.getByText("0.60")).toBeInTheDocument();
  });

  it("renders bandit best_ratio when snapshot present", async () => {
    retrainTickerState = {
      data: {
        ticker: "005930",
        success: true,
        new_policy_id: 42,
        excess_return: 0.012,
        walk_forward_passed: true,
        deployed: true,
        error: null,
        selected_train_ratio: 0.6,
        bandit_snapshot: makeSnapshot({ best_ratio: 0.7, epsilon: 0.15 }),
      },
      isPending: false,
      mutate: retrainTickerMutate,
    };

    renderPage();
    await openCycleTab();

    const bestRatioBadge = screen.getByText(/밴딧 best ratio/);
    expect(bestRatioBadge).toBeInTheDocument();
    // The <strong> with 0.70 lives inside the badge span
    expect(bestRatioBadge.querySelector("strong")?.textContent).toBe("0.70");
    expect(screen.getByText(/ε=0\.15/)).toBeInTheDocument();
    expect(screen.getByText(/펼쳐보기 \(밴딧 arms\)/)).toBeInTheDocument();
  });

  it("hides ratio badge when retrain failed", async () => {
    retrainTickerState = {
      data: {
        ticker: "005930",
        success: false,
        new_policy_id: null,
        excess_return: null,
        walk_forward_passed: false,
        deployed: false,
        error: "boom",
        selected_train_ratio: null,
        bandit_snapshot: null,
      },
      isPending: false,
      mutate: retrainTickerMutate,
    };

    renderPage();
    await openCycleTab();

    expect(screen.queryByText(/선택된 학습 비율/)).not.toBeInTheDocument();
    expect(screen.getByText(/실패: boom/)).toBeInTheDocument();
  });

  it("renders per-ticker ratios in batch retrain results", async () => {
    retrainAllState = {
      data: {
        total_tickers: 2,
        successful: 2,
        failed: 0,
        results: [
          {
            ticker: "005930",
            success: true,
            new_policy_id: 1,
            excess_return: 0.01,
            walk_forward_passed: true,
            deployed: true,
            error: null,
            selected_train_ratio: 0.6,
            bandit_snapshot: null,
          },
          {
            ticker: "000660",
            success: true,
            new_policy_id: 2,
            excess_return: 0.02,
            walk_forward_passed: true,
            deployed: true,
            error: null,
            selected_train_ratio: 0.8,
            bandit_snapshot: null,
          },
        ],
      },
      isPending: false,
      mutate: retrainAllMutate,
    };

    renderPage();
    await openCycleTab();

    expect(screen.getByText(/사이클 선택 비율/)).toBeInTheDocument();
    expect(screen.getByText(/005930: ratio=/)).toBeInTheDocument();
    expect(screen.getByText(/000660: ratio=/)).toBeInTheDocument();
    expect(screen.getByText("0.60")).toBeInTheDocument();
    expect(screen.getByText("0.80")).toBeInTheDocument();
  });
});

/**
 * ui/src/hooks/useBacktest.ts — Backtest 결과 조회 훅
 */
import { useQuery } from "@tanstack/react-query";
import { api } from "@/utils/api";

/* ── 타입 정의 ─────────────────────────────────────────────────────────── */

export interface BacktestRunSummary {
  id: number;
  ticker: string;
  strategy: string;
  test_start: string;
  test_end: string;
  total_return_pct: number;
  sharpe_ratio: number;
  max_drawdown_pct: number;
  win_rate: number;
  total_trades: number;
  created_at: string;
}

export interface BacktestRunDetail extends BacktestRunSummary {
  train_start: string;
  train_end: string;
  initial_capital: number;
  commission_rate_pct: number;
  tax_rate_pct: number;
  slippage_bps: number;
  annual_return_pct: number;
  avg_holding_days: number;
  baseline_return_pct: number;
  excess_return_pct: number;
}

export interface BacktestDailyItem {
  date: string;
  close_price: number;
  cash: number;
  position_qty: number;
  position_value: number;
  portfolio_value: number;
  daily_return_pct: number;
}

interface ListMeta {
  page: number;
  per_page: number;
  total: number;
}

interface ListResponse {
  data: BacktestRunSummary[];
  meta: ListMeta;
}

/* ── fetch 함수 ────────────────────────────────────────────────────────── */

async function fetchBacktestRuns(
  page: number,
  perPage: number,
  strategy?: string,
): Promise<ListResponse> {
  const params: Record<string, string | number> = { page, per_page: perPage };
  if (strategy) params.strategy = strategy;
  const { data } = await api.get<ListResponse>("/backtest/runs", { params });
  return data;
}

async function fetchBacktestDetail(runId: number): Promise<BacktestRunDetail> {
  const { data } = await api.get<BacktestRunDetail>(`/backtest/runs/${runId}`);
  return data;
}

async function fetchBacktestDaily(runId: number): Promise<BacktestDailyItem[]> {
  const { data } = await api.get<BacktestDailyItem[]>(`/backtest/runs/${runId}/daily`);
  return data;
}

/* ── Query 훅 ──────────────────────────────────────────────────────────── */

export function useBacktestRuns(page = 1, perPage = 20, strategy?: string) {
  return useQuery({
    queryKey: ["backtest", "runs", page, perPage, strategy],
    queryFn: () => fetchBacktestRuns(page, perPage, strategy),
    refetchInterval: 30_000,
  });
}

export function useBacktestDetail(runId: number | null) {
  return useQuery({
    queryKey: ["backtest", "detail", runId],
    queryFn: () => fetchBacktestDetail(runId as number),
    enabled: runId !== null,
  });
}

export function useBacktestDaily(runId: number | null) {
  return useQuery({
    queryKey: ["backtest", "daily", runId],
    queryFn: () => fetchBacktestDaily(runId as number),
    enabled: runId !== null,
  });
}

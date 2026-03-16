/**
 * ui/src/hooks/useFeedback.ts — 피드백 루프 데이터 조회/실행 훅
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/utils/api";

/* ── 타입 정의 ─────────────────────────────────────────────────────────── */

export interface AccuracyStats {
  strategy: string;
  total_predictions: number;
  correct_predictions: number;
  accuracy: number;
  signal_distribution: Record<string, number>;
  period_start: string;
  period_end: string;
}

export interface LLMFeedbackContext {
  strategy: string;
  feedback_text: string;
  error_patterns: string[];
  signal_bias: Record<string, number>;
  generated_at: string;
  cached: boolean;
}

export interface BacktestRequest {
  strategy: string;
  start_date?: string;
  end_date?: string;
  initial_capital?: number;
}

export interface BacktestResult {
  strategy: string;
  period: { start: string; end: string };
  initial_capital: number;
  final_capital: number;
  total_return: number;
  annualized_return: number;
  max_drawdown: number;
  sharpe_ratio: number | null;
  win_rate: number;
  profit_factor: number | null;
  total_trades: number;
  avg_holding_days: number | null;
}

export interface StrategyComparison {
  strategies: BacktestResult[];
  best_strategy: string;
  ranking: { strategy: string; total_return: number; rank: number }[];
}

export interface RetrainResultItem {
  ticker: string;
  success: boolean;
  new_policy_id: number | null;
  excess_return: number | null;
  walk_forward_passed: boolean;
  deployed: boolean;
  error: string | null;
}

export interface RetrainBatchResponse {
  total_tickers: number;
  successful: number;
  failed: number;
  results: RetrainResultItem[];
}

export interface FeedbackCycleResponse {
  scope: string;
  llm_feedback: { strategies_processed: number; cached: boolean } | null;
  rl_retrain: { tickers_retrained: number; successful: number } | null;
  backtest: { strategies_compared: number; best_strategy: string } | null;
  duration_seconds: number;
  saved_to_s3: boolean;
}

/* ── fetch 함수 ────────────────────────────────────────────────────────── */

async function fetchAccuracy(strategy?: string, days?: number): Promise<AccuracyStats[]> {
  const { data } = await api.get<AccuracyStats[]>("/feedback/accuracy", {
    params: { strategy, days },
  });
  return Array.isArray(data) ? data : [data];
}

async function fetchLLMContext(strategy: string): Promise<LLMFeedbackContext> {
  const { data } = await api.get<LLMFeedbackContext>(`/feedback/llm-context/${strategy}`);
  return data;
}

/* ── Query 훅 ──────────────────────────────────────────────────────────── */

export function useAccuracy(strategy?: string, days = 30) {
  return useQuery({
    queryKey: ["feedback", "accuracy", strategy, days],
    queryFn: () => fetchAccuracy(strategy, days),
    refetchInterval: 60_000,
  });
}

export function useLLMContext(strategy: string | null) {
  return useQuery({
    queryKey: ["feedback", "llm-context", strategy],
    queryFn: () => fetchLLMContext(strategy as string),
    enabled: strategy !== null,
    refetchInterval: 60_000,
  });
}

/* ── Mutation 훅 ───────────────────────────────────────────────────────── */

export function useRunBacktest() {
  return useMutation({
    mutationFn: async (payload: BacktestRequest) => {
      const { data } = await api.post<BacktestResult>("/feedback/backtest", payload);
      return data;
    },
  });
}

export function useCompareStrategies() {
  return useMutation({
    mutationFn: async (payload: { strategies?: string[]; start_date?: string; end_date?: string }) => {
      const { data } = await api.post<StrategyComparison>("/feedback/backtest/compare", payload);
      return data;
    },
  });
}

export function useRetrainTicker() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (ticker: string) => {
      const { data } = await api.post<RetrainResultItem>(`/feedback/rl/retrain/${ticker}`);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["rl", "policies"] });
      qc.invalidateQueries({ queryKey: ["feedback"] });
    },
  });
}

export function useRetrainAll() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data } = await api.post<RetrainBatchResponse>("/feedback/rl/retrain-all");
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["rl", "policies"] });
      qc.invalidateQueries({ queryKey: ["feedback"] });
    },
  });
}

export function useRunFeedbackCycle() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (scope: "full" | "llm_only" | "rl_only" | "backtest_only" = "full") => {
      const { data } = await api.post<FeedbackCycleResponse>("/feedback/cycle", { scope });
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["feedback"] });
      qc.invalidateQueries({ queryKey: ["rl"] });
    },
  });
}

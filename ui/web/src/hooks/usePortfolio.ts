/**
 * ui/src/hooks/usePortfolio.ts — 포트폴리오 데이터 조회 훅
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/utils/api";

export interface Position {
  ticker: string;
  name: string;
  quantity: number;
  avg_price: number;
  current_price: number;
  unrealized_pnl: number;
  weight_pct: number;
}

export interface PortfolioSummary {
  total_value: number;
  total_pnl: number;
  total_pnl_pct: number;
  is_paper: boolean;
  positions: Position[];
}

export interface PerformanceMetrics {
  period: "daily" | "weekly" | "monthly" | "all";
  return_pct: number;
  max_drawdown_pct: number;
  sharpe_ratio: number | null;
  win_rate: number;
  total_trades: number;
  kospi_benchmark_pct: number | null;
}

export interface PerformanceSeriesPoint {
  date: string;
  portfolio_return_pct: number;
  benchmark_return_pct: number | null;
  realized_pnl_cum: number;
  trade_count: number;
}

export interface TradeHistoryItem {
  ticker: string;
  name: string;
  side: "BUY" | "SELL";
  quantity: number;
  price: number;
  amount: number;
  signal_source: "A" | "B" | "BLEND" | null;
  agent_id: string | null;
  is_paper: boolean;
  circuit_breaker: boolean;
  executed_at: string;
}

export interface PortfolioConfig {
  strategy_blend_ratio: number;
  max_position_pct: number;
  daily_loss_limit_pct: number;
  is_paper_trading: boolean;
}

export interface TradingModePayload {
  is_paper: boolean;
  confirmation_code: string;
}

export interface ReadinessCheckItem {
  key: string;
  ok: boolean;
  message: string;
  severity: "critical" | "high" | "info" | string;
}

export interface ReadinessResult {
  ready: boolean;
  critical_ok: boolean;
  high_ok: boolean;
  checks: ReadinessCheckItem[];
}

async function fetchPortfolio(): Promise<PortfolioSummary> {
  const { data } = await api.get<PortfolioSummary>("/portfolio/positions");
  return data;
}

async function fetchPerformance(period: PerformanceMetrics["period"]): Promise<PerformanceMetrics> {
  const { data } = await api.get<PerformanceMetrics>("/portfolio/performance", { params: { period } });
  return data;
}

async function fetchPerformanceSeries(period: PerformanceMetrics["period"]): Promise<{
  period: PerformanceMetrics["period"];
  points: PerformanceSeriesPoint[];
}> {
  const { data } = await api.get("/portfolio/performance-series", { params: { period } });
  return data;
}

async function fetchTradeHistory(page = 1, perPage = 30): Promise<{
  data: TradeHistoryItem[];
  meta: { page: number; per_page: number };
}> {
  const { data } = await api.get("/portfolio/history", {
    params: { page, per_page: perPage },
  });
  return data;
}

async function fetchPortfolioConfig(): Promise<PortfolioConfig> {
  const { data } = await api.get<PortfolioConfig>("/portfolio/config");
  return data;
}

async function fetchReadiness(): Promise<ReadinessResult> {
  const { data } = await api.get<ReadinessResult>("/portfolio/readiness");
  return data;
}

export function usePortfolio() {
  return useQuery({
    queryKey: ["portfolio", "positions"],
    queryFn: fetchPortfolio,
    refetchInterval: 30_000,
  });
}

export function usePerformance(period: PerformanceMetrics["period"] = "monthly") {
  return useQuery({
    queryKey: ["portfolio", "performance", period],
    queryFn: () => fetchPerformance(period),
    refetchInterval: 30_000,
  });
}

export function usePerformanceSeries(period: PerformanceMetrics["period"] = "monthly") {
  return useQuery({
    queryKey: ["portfolio", "performance-series", period],
    queryFn: () => fetchPerformanceSeries(period),
    refetchInterval: 30_000,
  });
}

export function useTradeHistory(page = 1, perPage = 30) {
  return useQuery({
    queryKey: ["portfolio", "history", page, perPage],
    queryFn: () => fetchTradeHistory(page, perPage),
    refetchInterval: 30_000,
  });
}

export function usePortfolioConfig() {
  return useQuery({
    queryKey: ["portfolio", "config"],
    queryFn: fetchPortfolioConfig,
    refetchInterval: 30_000,
  });
}

export function useReadiness() {
  return useQuery({
    queryKey: ["portfolio", "readiness"],
    queryFn: fetchReadiness,
    refetchInterval: 60_000,
  });
}

export function useUpdatePortfolioConfig() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: Omit<PortfolioConfig, "is_paper_trading">) => {
      const { data } = await api.post("/portfolio/config", payload);
      return data;
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["portfolio", "config"] }),
        queryClient.invalidateQueries({ queryKey: ["portfolio", "positions"] }),
        queryClient.invalidateQueries({ queryKey: ["portfolio", "performance"] }),
      ]);
    },
  });
}

export function useUpdateTradingMode() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: TradingModePayload) => {
      const { data } = await api.post("/portfolio/trading-mode", payload);
      return data;
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["portfolio", "config"] }),
        queryClient.invalidateQueries({ queryKey: ["portfolio", "positions"] }),
        queryClient.invalidateQueries({ queryKey: ["portfolio", "readiness"] }),
      ]);
    },
  });
}

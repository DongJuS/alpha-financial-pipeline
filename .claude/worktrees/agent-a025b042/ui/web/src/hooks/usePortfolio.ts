/**
 * ui/src/hooks/usePortfolio.ts — 포트폴리오 데이터 조회 훅
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/utils/api";

export type TradingScope = "current" | "paper" | "real";
export type MarketSessionStatus = "open" | "closed" | "holiday" | "weekend" | "after_hours" | "pre_open";

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
  enable_paper_trading: boolean;
  enable_real_trading: boolean;
  primary_account_scope: "paper" | "real";
  market_hours_enforced: boolean;
  market_status: MarketSessionStatus;
}

export interface TradingModePayload {
  enable_paper_trading: boolean;
  enable_real_trading: boolean;
  primary_account_scope: "paper" | "real";
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

export interface PaperTradingRun {
  scenario: string;
  simulated_days: number;
  trade_count: number;
  return_pct: number;
  benchmark_return_pct: number | null;
  max_drawdown_pct: number | null;
  sharpe_ratio: number | null;
  passed: boolean;
  summary: string | null;
  created_at: string;
}

export interface PaperTradingOverview {
  broker: string;
  account_label: string;
  current_mode_is_paper: boolean;
  active_days_120d: number;
  trade_count_120d: number;
  traded_tickers_120d: number;
  last_executed_at: string | null;
  latest_run: PaperTradingRun | null;
}

export interface TradingAccountOverview {
  account_scope: TradingScope;
  broker_name: string;
  account_label: string;
  base_currency: string;
  seed_capital: number;
  cash_balance: number;
  buying_power: number;
  position_market_value: number;
  total_equity: number;
  realized_pnl: number;
  unrealized_pnl: number;
  total_pnl: number;
  total_pnl_pct: number;
  position_count: number;
  last_snapshot_at: string | null;
}

export interface BrokerOrderItem {
  client_order_id: string;
  account_scope: TradingScope;
  broker_name: string;
  ticker: string;
  name: string;
  side: "BUY" | "SELL";
  order_type: string;
  requested_quantity: number;
  requested_price: number;
  filled_quantity: number;
  avg_fill_price: number | null;
  status: "PENDING" | "FILLED" | "REJECTED" | "CANCELLED";
  signal_source: "A" | "B" | "BLEND" | null;
  agent_id: string | null;
  broker_order_id: string | null;
  rejection_reason: string | null;
  requested_at: string;
  filled_at: string | null;
}

export interface AccountSnapshotPoint {
  account_scope: TradingScope;
  cash_balance: number;
  buying_power: number;
  position_market_value: number;
  total_equity: number;
  realized_pnl: number;
  unrealized_pnl: number;
  position_count: number;
  snapshot_source: string;
  snapshot_at: string | null;
}

async function fetchPortfolio(mode: TradingScope = "current"): Promise<PortfolioSummary> {
  const { data } = await api.get<PortfolioSummary>("/portfolio/positions", {
    params: { mode },
  });
  return data;
}

async function fetchPerformance(
  period: PerformanceMetrics["period"],
  mode: TradingScope = "current"
): Promise<PerformanceMetrics> {
  const { data } = await api.get<PerformanceMetrics>("/portfolio/performance", { params: { period, mode } });
  return data;
}

async function fetchPerformanceSeries(period: PerformanceMetrics["period"], mode: TradingScope = "current"): Promise<{
  period: PerformanceMetrics["period"];
  points: PerformanceSeriesPoint[];
}> {
  const { data } = await api.get("/portfolio/performance-series", { params: { period, mode } });
  return data;
}

async function fetchTradeHistory(page = 1, perPage = 30, mode: TradingScope = "current"): Promise<{
  data: TradeHistoryItem[];
  meta: { page: number; per_page: number };
}> {
  const { data } = await api.get("/portfolio/history", {
    params: { page, per_page: perPage, mode },
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

async function fetchPaperTradingOverview(): Promise<PaperTradingOverview> {
  const { data } = await api.get<PaperTradingOverview>("/portfolio/paper-overview");
  return data;
}

async function fetchTradingAccountOverview(mode: TradingScope = "current"): Promise<TradingAccountOverview> {
  const { data } = await api.get<TradingAccountOverview>("/portfolio/account-overview", { params: { mode } });
  return data;
}

async function fetchBrokerOrders(mode: TradingScope = "current", limit = 50): Promise<{
  account_scope: TradingScope;
  data: BrokerOrderItem[];
}> {
  const { data } = await api.get("/portfolio/orders", { params: { mode, limit } });
  return data;
}

async function fetchAccountSnapshots(mode: TradingScope = "current", limit = 30): Promise<{
  account_scope: TradingScope;
  points: AccountSnapshotPoint[];
}> {
  const { data } = await api.get("/portfolio/account-snapshots", { params: { mode, limit } });
  return data;
}

export function usePortfolio(mode: TradingScope = "current") {
  return useQuery({
    queryKey: ["portfolio", "positions", mode],
    queryFn: () => fetchPortfolio(mode),
    refetchInterval: 30_000,
  });
}

export function usePerformance(period: PerformanceMetrics["period"] = "monthly", mode: TradingScope = "current") {
  return useQuery({
    queryKey: ["portfolio", "performance", period, mode],
    queryFn: () => fetchPerformance(period, mode),
    refetchInterval: 30_000,
  });
}

export function usePerformanceSeries(
  period: PerformanceMetrics["period"] = "monthly",
  mode: TradingScope = "current"
) {
  return useQuery({
    queryKey: ["portfolio", "performance-series", period, mode],
    queryFn: () => fetchPerformanceSeries(period, mode),
    refetchInterval: 30_000,
  });
}

export function useTradeHistory(page = 1, perPage = 30, mode: TradingScope = "current") {
  return useQuery({
    queryKey: ["portfolio", "history", page, perPage, mode],
    queryFn: () => fetchTradeHistory(page, perPage, mode),
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

export function usePaperTradingOverview() {
  return useQuery({
    queryKey: ["portfolio", "paper-overview"],
    queryFn: fetchPaperTradingOverview,
    refetchInterval: 60_000,
  });
}

export function useTradingAccountOverview(mode: TradingScope = "current") {
  return useQuery({
    queryKey: ["portfolio", "account-overview", mode],
    queryFn: () => fetchTradingAccountOverview(mode),
    refetchInterval: 30_000,
  });
}

export function useBrokerOrders(mode: TradingScope = "current", limit = 50) {
  return useQuery({
    queryKey: ["portfolio", "orders", mode, limit],
    queryFn: () => fetchBrokerOrders(mode, limit),
    refetchInterval: 30_000,
  });
}

export function useAccountSnapshots(mode: TradingScope = "current", limit = 30) {
  return useQuery({
    queryKey: ["portfolio", "account-snapshots", mode, limit],
    queryFn: () => fetchAccountSnapshots(mode, limit),
    refetchInterval: 30_000,
  });
}

export function useUpdatePortfolioConfig() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: Pick<PortfolioConfig, "strategy_blend_ratio" | "max_position_pct" | "daily_loss_limit_pct">) => {
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

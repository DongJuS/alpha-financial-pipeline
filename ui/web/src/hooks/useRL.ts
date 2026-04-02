/**
 * ui/src/hooks/useRL.ts — RL Trading 데이터 조회/실행 훅
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/utils/api";

/* ── 타입 정의 ─────────────────────────────────────────────────────────── */

export interface RLPolicy {
  id: number | string;
  ticker: string;
  version: string;
  algorithm: string;
  mode: "shadow" | "paper" | "real";
  is_active: boolean;
  excess_return: number | null;
  sharpe_ratio: number | null;
  max_drawdown: number | null;
  win_rate: number | null;
  total_trades: number;
  training_episodes: number;
  walk_forward_passed: boolean;
  created_at: string;
  activated_at: string | null;
}

export interface RLExperiment {
  run_id: string;
  ticker: string;
  algorithm: string;
  status: "running" | "completed" | "failed";
  episodes: number;
  best_reward: number | null;
  final_loss: number | null;
  started_at: string;
  completed_at: string | null;
  config: Record<string, unknown>;
}

export interface RLEvaluation {
  id: number;
  policy_id: number;
  ticker: string;
  period_start: string;
  period_end: string;
  total_return: number;
  benchmark_return: number;
  excess_return: number;
  sharpe_ratio: number | null;
  max_drawdown: number;
  win_rate: number;
  trade_count: number;
  evaluated_at: string;
}

export interface TrainingJobRequest {
  ticker: string;
  algorithm?: string;
  episodes?: number;
  lookback_days?: number;
}

export interface TrainingJob {
  job_id: string;
  /** 단일 학습 작업 상태 조회 시 반환 */
  ticker?: string;
  algorithm?: string;
  progress_pct?: number;
  started_at?: string | null;
  result_policy_id?: number | null;
  error?: string | null;
  /** 목록 조회 시 반환 (백엔드 실제 필드) */
  tickers?: string[];
  policy_family?: string;
  dataset_interval?: string;
  dataset_days?: number;
  created_at?: string;
  status: "queued" | "running" | "completed" | "failed";
  completed_at: string | null;
}

export interface WalkForwardRequest {
  ticker: string;
  n_folds?: number;
  dataset_days?: number;
}

export interface WalkForwardResult {
  /** 백엔드 실제 필드 */
  n_folds: number;
  total_data_points: number;
  avg_return_pct: number;
  std_return_pct: number;
  min_return_pct: number;
  max_return_pct: number;
  avg_excess_return_pct: number;
  avg_max_drawdown_pct: number;
  avg_win_rate: number;
  approved_folds: number;
  consistency_score: number;
  overall_approved: boolean;
  created_at: string;
  folds: unknown[];
  /** 하위 호환용 alias */
  passed?: boolean;
  avg_return?: number;
}

export interface ShadowSignalRequest {
  policy_id: number;
  ticker: string;
}

export interface ShadowPolicy {
  policy_id: number;
  ticker: string;
  mode: string;
  signal_count: number;
  avg_confidence: number | null;
  last_signal_at: string | null;
}

export interface ShadowPerformance {
  policy_id: number;
  ticker: string;
  total_signals: number;
  correct_signals: number;
  accuracy: number;
  virtual_return: number;
  benchmark_return: number;
  excess_return: number;
  period_days: number;
}

export interface ShadowRecord {
  id: number;
  policy_id: number;
  ticker: string;
  signal: "BUY" | "SELL" | "HOLD";
  confidence: number;
  actual_return: number | null;
  was_correct: boolean | null;
  created_at: string;
}

export interface PromotionResult {
  policy_id: string;
  ticker: string;
  promotion_type: string;
  /** 백엔드 필드: passed (shadow→paper, paper→real 공통) */
  passed: boolean;
  /** 백엔드 필드: failures 배열 */
  failures: string[];
  criteria: Record<string, unknown>;
  actual: Record<string, unknown>;
  checked_at: string;
  /** 하위 호환용 alias — 일부 응답에만 존재 */
  approved?: boolean;
  reason?: string;
}

export interface PolicyMode {
  policy_id: number;
  current_mode: string;
  can_promote_to: string | null;
  promotion_requirements: Record<string, unknown>;
}

/* ── fetch 함수 ────────────────────────────────────────────────────────── */

interface ListApiResponse<T> {
  data: T[];
  meta: Record<string, unknown>;
}

/** 백엔드 PolicySummary → 프론트엔드 RLPolicy 매핑 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function mapPolicy(raw: any): RLPolicy {
  return {
    id: raw.policy_id ?? raw.id,
    ticker: raw.ticker,
    version: raw.state_version ?? raw.version ?? "",
    algorithm: raw.algorithm,
    mode: raw.mode ?? (raw.is_active ? "paper" : "shadow"),
    is_active: raw.is_active ?? false,
    excess_return: raw.excess_return ?? raw.excess_return_pct ?? raw.return_pct ?? null,
    sharpe_ratio: raw.sharpe_ratio ?? null,
    max_drawdown: raw.max_drawdown ?? raw.max_drawdown_pct ?? null,
    win_rate: raw.win_rate ?? null,
    total_trades: raw.total_trades ?? raw.trades ?? 0,
    training_episodes: raw.training_episodes ?? raw.episodes ?? 0,
    walk_forward_passed: raw.walk_forward_passed ?? raw.approved ?? false,
    created_at: raw.created_at,
    activated_at: raw.activated_at ?? null,
  };
}

async function fetchPolicies(): Promise<RLPolicy[]> {
  const { data } = await api.get<ListApiResponse<Record<string, unknown>>>("/rl/policies");
  const items = Array.isArray(data) ? data : (data?.data ?? []);
  return items.map(mapPolicy);
}

async function fetchActivePolicies(): Promise<RLPolicy[]> {
  const { data } = await api.get<ListApiResponse<Record<string, unknown>>>("/rl/policies/active");
  const items = Array.isArray(data) ? data : (data?.data ?? []);
  return items.map(mapPolicy);
}

async function fetchTickerPolicies(ticker: string): Promise<RLPolicy[]> {
  const { data } = await api.get<ListApiResponse<Record<string, unknown>>>(`/rl/policies/${ticker}`);
  const items = Array.isArray(data) ? data : (data?.data ?? []);
  return items.map(mapPolicy);
}

async function fetchExperiments(): Promise<RLExperiment[]> {
  const { data } = await api.get<ListApiResponse<RLExperiment>>("/rl/experiments");
  return Array.isArray(data) ? data : (data?.data ?? []);
}

async function fetchExperiment(runId: string): Promise<RLExperiment> {
  const { data } = await api.get<RLExperiment>(`/rl/experiments/${runId}`);
  return data;
}

async function fetchEvaluations(): Promise<RLEvaluation[]> {
  const { data } = await api.get<ListApiResponse<RLEvaluation>>("/rl/evaluations");
  return Array.isArray(data) ? data : (data?.data ?? []);
}

async function fetchShadowPolicies(): Promise<ShadowPolicy[]> {
  const { data } = await api.get<ListApiResponse<ShadowPolicy>>("/rl/shadow/policies");
  return Array.isArray(data) ? data : (data?.data ?? []);
}

async function fetchShadowPerformance(policyId: number): Promise<ShadowPerformance> {
  const { data } = await api.get<ShadowPerformance>(`/rl/shadow/performance/${policyId}`);
  return data;
}

async function fetchShadowRecords(policyId: number): Promise<ShadowRecord[]> {
  const { data } = await api.get<ShadowRecord[]>(`/rl/shadow/records/${policyId}`);
  return data;
}

async function fetchTrainingJob(jobId: string): Promise<TrainingJob> {
  const { data } = await api.get<TrainingJob>(`/rl/training-jobs/${jobId}`);
  return data;
}

async function fetchPolicyMode(policyId: number | string, ticker: string): Promise<PolicyMode> {
  const { data } = await api.get<PolicyMode>(
    `/rl/promotion/policy-mode/${policyId}?ticker=${encodeURIComponent(ticker)}`,
  );
  return data;
}

/* ── Query 훅 ──────────────────────────────────────────────────────────── */

export function usePolicies() {
  return useQuery({
    queryKey: ["rl", "policies"],
    queryFn: fetchPolicies,
    refetchInterval: 30_000,
  });
}

export function useActivePolicies() {
  return useQuery({
    queryKey: ["rl", "policies", "active"],
    queryFn: fetchActivePolicies,
    refetchInterval: 30_000,
  });
}

export function useTickerPolicies(ticker: string | null) {
  return useQuery({
    queryKey: ["rl", "policies", ticker],
    queryFn: () => fetchTickerPolicies(ticker as string),
    enabled: ticker !== null,
    refetchInterval: 30_000,
  });
}

export function useExperiments() {
  return useQuery({
    queryKey: ["rl", "experiments"],
    queryFn: fetchExperiments,
    refetchInterval: 15_000,
  });
}

export function useExperiment(runId: string | null) {
  return useQuery({
    queryKey: ["rl", "experiment", runId],
    queryFn: () => fetchExperiment(runId as string),
    enabled: runId !== null,
    refetchInterval: 5_000,
  });
}

export function useEvaluations() {
  return useQuery({
    queryKey: ["rl", "evaluations"],
    queryFn: fetchEvaluations,
    refetchInterval: 60_000,
  });
}

export function useShadowPolicies() {
  return useQuery({
    queryKey: ["rl", "shadow", "policies"],
    queryFn: fetchShadowPolicies,
    refetchInterval: 30_000,
  });
}

export function useShadowPerformance(policyId: number | null) {
  return useQuery({
    queryKey: ["rl", "shadow", "performance", policyId],
    queryFn: () => fetchShadowPerformance(policyId as number),
    enabled: policyId !== null,
    refetchInterval: 60_000,
  });
}

export function useShadowRecords(policyId: number | null) {
  return useQuery({
    queryKey: ["rl", "shadow", "records", policyId],
    queryFn: () => fetchShadowRecords(policyId as number),
    enabled: policyId !== null,
  });
}

export function useTrainingJob(jobId: string | null) {
  return useQuery({
    queryKey: ["rl", "training-job", jobId],
    queryFn: () => fetchTrainingJob(jobId as string),
    enabled: jobId !== null,
    refetchInterval: 3_000,
  });
}

export function useTrainingJobs() {
  return useQuery({
    queryKey: ["rl", "training-jobs"],
    queryFn: async () => {
      const { data } = await api.get<{ data: TrainingJob[]; total: number }>("/rl/training-jobs");
      return Array.isArray(data) ? data : (data?.data ?? []);
    },
    refetchInterval: 5_000,
  });
}

export function usePolicyMode(policyId: number | string | null, ticker: string | null) {
  return useQuery({
    queryKey: ["rl", "policy-mode", policyId, ticker],
    queryFn: () => fetchPolicyMode(policyId as number | string, ticker as string),
    enabled: policyId !== null && ticker !== null,
  });
}

/* ── Mutation 훅 ───────────────────────────────────────────────────────── */

export function useActivatePolicy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ policyId, ticker }: { policyId: number | string; ticker: string }) => {
      const { data } = await api.post(
        `/rl/policies/${policyId}/activate?ticker=${encodeURIComponent(ticker)}`,
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["rl", "policies"] });
    },
  });
}

export function useCreateTrainingJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: TrainingJobRequest) => {
      // 백엔드 TrainingJobRequest 스키마에 맞게 변환
      const backendPayload = {
        tickers: [payload.ticker],
        policy_family: payload.algorithm ?? "tabular_q_v2",
        dataset_interval: "daily" as const,
        dataset_days: payload.lookback_days ?? 120,
      };
      const { data } = await api.post<TrainingJob>("/rl/training-jobs", backendPayload);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["rl", "experiments"] });
      qc.invalidateQueries({ queryKey: ["rl", "training-jobs"] });
    },
  });
}

export function useRunWalkForward() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: WalkForwardRequest) => {
      // 백엔드 WalkForwardRequestModel 스키마에 맞게 변환
      const backendPayload = {
        ticker: payload.ticker,
        n_folds: payload.n_folds ?? 5,
        expanding_window: true,
        trainer_version: "v2" as const,
        dataset_days: payload.dataset_days ?? 120,
      };
      const { data } = await api.post<WalkForwardResult>("/rl/walk-forward", backendPayload);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["rl", "evaluations"] });
    },
  });
}

export function useCreateShadowSignal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: ShadowSignalRequest) => {
      const { data } = await api.post("/rl/shadow/signals", payload);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["rl", "shadow"] });
    },
  });
}

export function usePromoteShadowToPaper() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: { policy_id: number | string; ticker: string }) => {
      const { data } = await api.post<PromotionResult>("/rl/promotion/shadow-to-paper", {
        policy_id: String(payload.policy_id),
        ticker: payload.ticker,
      });
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["rl"] });
    },
  });
}

/* ── RL 종목 관리 ──────────────────────────────────────────────────────── */

export interface RLTickerInfo {
  ticker: string;
  active_policy_id: string | null;
  has_policy: boolean;
}

export function useRLTickers() {
  return useQuery({
    queryKey: ["rl", "tickers"],
    queryFn: async (): Promise<RLTickerInfo[]> => {
      const { data } = await api.get<{ tickers: RLTickerInfo[]; total: number }>("/rl/tickers");
      return data.tickers ?? [];
    },
    refetchInterval: 30_000,
  });
}

export function useAddRLTickers() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (tickers: string[]) => {
      const { data } = await api.put("/rl/tickers", { tickers });
      return data as { tickers: string[]; added: string[]; total: number };
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["rl", "tickers"] });
      qc.invalidateQueries({ queryKey: ["rl", "policies"] });
    },
  });
}

export function useRemoveRLTicker() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (ticker: string) => {
      const { data } = await api.delete(`/rl/tickers/${encodeURIComponent(ticker)}`);
      return data as { removed: string; remaining: string[]; total: number };
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["rl", "tickers"] });
      qc.invalidateQueries({ queryKey: ["rl", "policies"] });
    },
  });
}

export function usePromotePaperToReal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: {
      policy_id: number | string;
      ticker: string;
      confirmation_code?: string;
    }) => {
      const { data } = await api.post<PromotionResult>("/rl/promotion/paper-to-real", {
        policy_id: String(payload.policy_id),
        ticker: payload.ticker,
      });
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["rl"] });
    },
  });
}

/* ── 종목 선택용 마켓 종목 조회 ─────────────────────────────────────── */

export interface MarketTickerItem {
  ticker: string;
  name: string;
  market: string;
}

export function useMarketTickers(enabled = true) {
  return useQuery({
    queryKey: ["market", "tickers-all"],
    queryFn: async (): Promise<MarketTickerItem[]> => {
      const { data } = await api.get<{ data: MarketTickerItem[] }>("/market/tickers", {
        params: { per_page: 200 },
      });
      return data?.data ?? [];
    },
    enabled,
    staleTime: 60_000,
  });
}

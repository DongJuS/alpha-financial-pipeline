/**
 * ui/src/hooks/useRL.ts — RL Trading 데이터 조회/실행 훅
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/utils/api";

/* ── 타입 정의 ─────────────────────────────────────────────────────────── */

export interface RLPolicy {
  id: number;
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
  ticker: string;
  algorithm: string;
  status: "queued" | "running" | "completed" | "failed";
  progress_pct: number;
  started_at: string | null;
  completed_at: string | null;
  result_policy_id: number | null;
  error: string | null;
}

export interface WalkForwardRequest {
  policy_id: number;
  n_splits?: number;
}

export interface WalkForwardResult {
  policy_id: number;
  passed: boolean;
  splits: number;
  avg_return: number;
  worst_split_return: number;
  consistency_score: number;
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
  policy_id: number;
  from_mode: string;
  to_mode: string;
  approved: boolean;
  reason: string;
  metrics: Record<string, unknown>;
}

export interface PolicyMode {
  policy_id: number;
  current_mode: string;
  can_promote_to: string | null;
  promotion_requirements: Record<string, unknown>;
}

/* ── fetch 함수 ────────────────────────────────────────────────────────── */

async function fetchPolicies(): Promise<RLPolicy[]> {
  const { data } = await api.get<RLPolicy[]>("/rl/policies");
  return data;
}

async function fetchActivePolicies(): Promise<RLPolicy[]> {
  const { data } = await api.get<RLPolicy[]>("/rl/policies/active");
  return data;
}

async function fetchTickerPolicies(ticker: string): Promise<RLPolicy[]> {
  const { data } = await api.get<RLPolicy[]>(`/rl/policies/${ticker}`);
  return data;
}

async function fetchExperiments(): Promise<RLExperiment[]> {
  const { data } = await api.get<RLExperiment[]>("/rl/experiments");
  return data;
}

async function fetchExperiment(runId: string): Promise<RLExperiment> {
  const { data } = await api.get<RLExperiment>(`/rl/experiments/${runId}`);
  return data;
}

async function fetchEvaluations(): Promise<RLEvaluation[]> {
  const { data } = await api.get<RLEvaluation[]>("/rl/evaluations");
  return data;
}

async function fetchShadowPolicies(): Promise<ShadowPolicy[]> {
  const { data } = await api.get<ShadowPolicy[]>("/rl/shadow/policies");
  return data;
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

async function fetchPolicyMode(policyId: number): Promise<PolicyMode> {
  const { data } = await api.get<PolicyMode>(`/rl/promotion/policy-mode/${policyId}`);
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

export function usePolicyMode(policyId: number | null) {
  return useQuery({
    queryKey: ["rl", "policy-mode", policyId],
    queryFn: () => fetchPolicyMode(policyId as number),
    enabled: policyId !== null,
  });
}

/* ── Mutation 훅 ───────────────────────────────────────────────────────── */

export function useActivatePolicy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (policyId: number) => {
      const { data } = await api.post(`/rl/policies/${policyId}/activate`);
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
      const { data } = await api.post<TrainingJob>("/rl/training-jobs", payload);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["rl", "experiments"] });
    },
  });
}

export function useRunWalkForward() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: WalkForwardRequest) => {
      const { data } = await api.post<WalkForwardResult>("/rl/walk-forward", payload);
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
    mutationFn: async (payload: { policy_id: number }) => {
      const { data } = await api.post<PromotionResult>("/rl/promotion/shadow-to-paper", payload);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["rl"] });
    },
  });
}

export function usePromotePaperToReal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: { policy_id: number; confirmation_code: string }) => {
      const { data } = await api.post<PromotionResult>("/rl/promotion/paper-to-real", payload);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["rl"] });
    },
  });
}

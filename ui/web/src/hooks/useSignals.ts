/**
 * ui/src/hooks/useSignals.ts — 전략 시그널 조회 훅
 */
import { useQuery } from "@tanstack/react-query";
import { api } from "@/utils/api";

export interface CombinedSignal {
  ticker: string;
  strategy_a_signal: string | null;
  strategy_b_signal: string | null;
  combined_signal: string;
  combined_confidence: number | null;
  conflict: boolean;
}

export interface TournamentRank {
  agent_id: string;
  llm_model: string;
  persona: string;
  rolling_accuracy: number | null;
  correct: number;
  total: number;
  is_current_winner: boolean;
}

export interface StrategyBSignal {
  agent_id: string;
  llm_model: string;
  ticker: string;
  signal: "BUY" | "SELL" | "HOLD";
  confidence: number | null;
  reasoning_summary: string | null;
  trading_date: string;
  debate_transcript_id: number | null;
}

export interface DebateTranscript {
  id: number;
  date: string;
  ticker: string;
  rounds: number;
  consensus_reached: boolean;
  final_signal: string | null;
  confidence: number | null;
  proposer_content: string | null;
  challenger1_content: string | null;
  challenger2_content: string | null;
  synthesizer_content: string | null;
  no_consensus_reason: string | null;
  created_at: string;
}

export interface DebateListItem {
  id: number;
  date: string;
  ticker: string;
  rounds: number;
  consensus_reached: boolean;
  final_signal: string | null;
  confidence: number | null;
  no_consensus_reason: string | null;
  created_at: string;
}

async function fetchCombinedSignals(): Promise<{
  blend_ratio: number;
  signals: CombinedSignal[];
}> {
  const { data } = await api.get("/strategy/combined");
  return data;
}

async function fetchTournament(): Promise<{
  period_days: number;
  rankings: TournamentRank[];
}> {
  const { data } = await api.get("/strategy/a/tournament");
  return data;
}

async function fetchStrategyBSignals(): Promise<{
  date: string;
  signals: StrategyBSignal[];
}> {
  const { data } = await api.get("/strategy/b/signals");
  return data;
}

async function fetchDebateTranscript(debateId: number): Promise<DebateTranscript> {
  const { data } = await api.get(`/strategy/b/debate/${debateId}`);
  return data;
}

async function fetchDebateList(limit = 30): Promise<{ items: DebateListItem[] }> {
  const { data } = await api.get("/strategy/b/debates", { params: { limit } });
  return data;
}

export function useCombinedSignals() {
  return useQuery({
    queryKey: ["strategy", "combined"],
    queryFn: fetchCombinedSignals,
    refetchInterval: 60_000,
  });
}

export function useTournament() {
  return useQuery({
    queryKey: ["strategy", "tournament"],
    queryFn: fetchTournament,
    refetchInterval: 60_000,
  });
}

export function useStrategyBSignals() {
  return useQuery({
    queryKey: ["strategy", "b-signals"],
    queryFn: fetchStrategyBSignals,
    refetchInterval: 60_000,
  });
}

export function useDebateTranscript(debateId: number | null) {
  return useQuery({
    queryKey: ["strategy", "debate", debateId],
    queryFn: () => fetchDebateTranscript(debateId as number),
    enabled: debateId !== null,
  });
}

export function useDebateList(limit = 30) {
  return useQuery({
    queryKey: ["strategy", "debates", limit],
    queryFn: () => fetchDebateList(limit),
    refetchInterval: 60_000,
  });
}

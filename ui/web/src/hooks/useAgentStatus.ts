/**
 * ui/src/hooks/useAgentStatus.ts — 에이전트 헬스 상태 폴링 훅
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/utils/api";

export interface AgentStatus {
  agent_id: string;
  status: "healthy" | "degraded" | "dead";
  is_alive: boolean;
  activity_state:
    | "offline"
    | "error"
    | "investing"
    | "collecting"
    | "analyzing"
    | "notifying"
    | "orchestrating"
    | "scheduled_wait"
    | "on_demand"
    | "active"
    | "degraded"
    | "idle";
  activity_label: string;
  last_action: string | null;
  metrics: { api_latency_ms: number | null; error_count_last_hour: number } | null;
  updated_at: string | null;
}

async function fetchAgentStatus(): Promise<AgentStatus[]> {
  const { data } = await api.get<{ agents: AgentStatus[] }>("/agents/status");
  return data.agents;
}

export function useAgentStatus() {
  return useQuery({
    queryKey: ["agents", "status"],
    queryFn: fetchAgentStatus,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}

/* ── 에이전트 로그 조회 ─────────────────────────────────────────────────── */

export interface AgentLogEntry {
  timestamp: string;
  level: string;
  message: string;
}

async function fetchAgentLogs(agentId: string): Promise<AgentLogEntry[]> {
  const { data } = await api.get<AgentLogEntry[]>(`/agents/${agentId}/logs`);
  return data;
}

export function useAgentLogs(agentId: string | null) {
  return useQuery({
    queryKey: ["agents", "logs", agentId],
    queryFn: () => fetchAgentLogs(agentId as string),
    enabled: agentId !== null,
    refetchInterval: 30_000,
  });
}

/* ── 에이전트 재시작 ────────────────────────────────────────────────────── */

export function useRestartAgent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (agentId: string) => {
      const { data } = await api.post(`/agents/${agentId}/restart`);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agents", "status"] });
    },
  });
}

/* ── Dual Execution 실행 ────────────────────────────────────────────────── */

export function useRunDualExecution() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data } = await api.post("/agents/dual-execution/run");
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agents", "status"] });
    },
  });
}

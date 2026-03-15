/**
 * ui/src/hooks/useSystemHealth.ts — 시스템 헬스 모니터링 훅
 */
import { useQuery } from "@tanstack/react-query";
import { api } from "@/utils/api";

export interface ServiceStatus {
  name: string;
  status: "ok" | "error" | "degraded";
  latency_ms: number | null;
  details: Record<string, unknown> | null;
}

export interface AgentSummary {
  total: number;
  alive: number;
  dead: number;
  degraded: number;
}

export interface SystemHealthOverview {
  overall_status: string;
  services: ServiceStatus[];
  agent_summary: AgentSummary;
  last_orchestrator_cycle: string | null;
  uptime_seconds: number | null;
}

export interface SystemMetrics {
  error_count_24h: number;
  total_heartbeats_24h: number;
  active_agents: number;
  db_table_count: number;
  recent_errors: Array<Record<string, unknown>>;
}

export function useSystemHealthOverview() {
  return useQuery({
    queryKey: ["system", "health", "overview"],
    queryFn: async (): Promise<SystemHealthOverview> => {
      const { data } = await api.get<SystemHealthOverview>("/system/overview");
      return data;
    },
    refetchInterval: 30_000,
    staleTime: 15_000,
  });
}

export function useSystemMetrics() {
  return useQuery({
    queryKey: ["system", "health", "metrics"],
    queryFn: async (): Promise<SystemMetrics> => {
      const { data } = await api.get<SystemMetrics>("/system/metrics");
      return data;
    },
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}

/**
 * ui/src/hooks/useAudit.ts — 감사 추적 훅
 */
import { useQuery } from "@tanstack/react-query";
import { api } from "@/utils/api";

export interface AuditTrailItem {
  event_type: string;
  event_time: string | null;
  agent_id: string | null;
  description: string | null;
  result: string | null;
}

export interface AuditTrailResponse {
  data: AuditTrailItem[];
  total: number;
  page: number;
  limit: number;
}

export interface AuditSummary {
  total_events: number;
  pass_rate: number | null;
  by_type: Record<string, number>;
}

interface AuditTrailParams {
  page?: number;
  limit?: number;
  event_type?: string;
  date_from?: string;
  date_to?: string;
}

export function useAuditTrail(params: AuditTrailParams = {}) {
  return useQuery({
    queryKey: ["audit", "trail", params],
    queryFn: async (): Promise<AuditTrailResponse> => {
      const { data } = await api.get<AuditTrailResponse>("/audit/trail", { params });
      return data;
    },
    staleTime: 30_000,
  });
}

export function useAuditSummary() {
  return useQuery({
    queryKey: ["audit", "summary"],
    queryFn: async (): Promise<AuditSummary> => {
      const { data } = await api.get<AuditSummary>("/audit/summary");
      return data;
    },
    refetchInterval: 120_000,
    staleTime: 60_000,
  });
}

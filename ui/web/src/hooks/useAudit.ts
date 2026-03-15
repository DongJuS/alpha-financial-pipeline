/**
 * ui/src/hooks/useAudit.ts — 감사 추적 훅
 */
import { useQuery } from "@tanstack/react-query";
import { api } from "@/utils/api";

export interface AuditTrailItem {
  id: number;
  audit_type: string;
  event_source: string;
  summary: string;
  details: Record<string, unknown> | null;
  success: boolean | null;
  actor: string | null;
  created_at: string;
}

export interface AuditTrailResponse {
  items: AuditTrailItem[];
  total: number;
  page: number;
  per_page: number;
}

export interface AuditSummary {
  total_events: number;
  events_24h: number;
  events_7d: number;
  by_type: Record<string, number>;
  pass_rate: number | null;
}

export function useAuditTrail(params: {
  audit_type?: string;
  from?: string;
  to?: string;
  page?: number;
  per_page?: number;
}) {
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
    staleTime: 60_000,
  });
}

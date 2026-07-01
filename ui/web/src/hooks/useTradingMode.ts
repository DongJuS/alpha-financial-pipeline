/**
 * ui/src/hooks/useTradingMode.ts — trading mode (paper/real) 조회 + 전환
 *
 * GET  /api/v1/system/trading-mode  — 현재 mode
 * POST /api/v1/system/trading-mode  — 전환
 *
 * Redis 에 저장되어 즉시 모든 pod 에서 반영. UI header 의 토글 컴포넌트에서 사용.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/utils/api";

export type TradingMode = "paper" | "real";

export interface TradingModeResponse {
  mode: TradingMode;
}

const QUERY_KEY = ["system", "trading-mode"] as const;

export function useTradingMode() {
  return useQuery({
    queryKey: QUERY_KEY,
    queryFn: async (): Promise<TradingMode> => {
      const { data } = await api.get<TradingModeResponse>("/system/trading-mode");
      return data.mode;
    },
    staleTime: 10_000,
    refetchOnWindowFocus: true,
  });
}

export function useSetTradingMode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (mode: TradingMode): Promise<TradingMode> => {
      const { data } = await api.post<TradingModeResponse>("/system/trading-mode", { mode });
      return data.mode;
    },
    onSuccess: (mode) => {
      qc.setQueryData(QUERY_KEY, mode);
      // /health 의 paper_trading 필드도 갱신되므로 관련 훅들 invalidate
      qc.invalidateQueries({ queryKey: ["system", "health"] });
    },
  });
}

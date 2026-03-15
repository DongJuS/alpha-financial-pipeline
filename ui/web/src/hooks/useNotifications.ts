/**
 * ui/src/hooks/useNotifications.ts — 알림 관련 훅
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/utils/api";

export interface NotificationPreferences {
  morning_brief: boolean;
  trade_alerts: boolean;
  circuit_breaker: boolean;
  daily_report: boolean;
  weekly_summary: boolean;
}

export interface NotificationStats {
  total_sent: number;
  success_rate: number | null;
  by_type: Record<string, number>;
  daily_trend: Array<{ date: string; cnt: number; success_cnt: number }>;
}

export interface NotificationHistoryItem {
  event_type: string;
  message: string;
  success: boolean;
  error_msg: string | null;
  sent_at: string;
  channel?: string;
  status?: string;
}

export function useNotificationPreferences() {
  return useQuery({
    queryKey: ["notifications", "preferences"],
    queryFn: async (): Promise<NotificationPreferences> => {
      const { data } = await api.get<{ preferences: NotificationPreferences }>("/notifications/preferences");
      return data.preferences;
    },
    refetchInterval: 60_000,
  });
}

export function useUpdateNotificationPreferences() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: NotificationPreferences) => {
      const { data } = await api.put("/notifications/preferences", payload);
      return data;
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["notifications", "preferences"] });
    },
  });
}

export function useNotificationStats() {
  return useQuery({
    queryKey: ["notifications", "stats"],
    queryFn: async (): Promise<NotificationStats> => {
      const { data } = await api.get<NotificationStats>("/notifications/stats");
      return data;
    },
    refetchInterval: 120_000,
    staleTime: 60_000,
  });
}

export function useNotificationHistory(limit: number = 20) {
  return useQuery({
    queryKey: ["notifications", "history", limit],
    queryFn: async (): Promise<NotificationHistoryItem[]> => {
      const { data } = await api.get<{ notifications: NotificationHistoryItem[] }>("/notifications/history", {
        params: { limit },
      });
      return data.notifications;
    },
    staleTime: 30_000,
  });
}

export function useSendTestNotification() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: { message: string; channel?: string }) => {
      const { data } = await api.post("/notifications/test", { message: payload.message });
      return data;
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["notifications", "history"] });
    },
  });
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/utils/api";

export interface NotificationPreferences {
  morning_brief: boolean;
  trade_alerts: boolean;
  circuit_breaker: boolean;
  daily_report: boolean;
  weekly_summary: boolean;
}

async function fetchPreferences(): Promise<NotificationPreferences> {
  const { data } = await api.get<{ preferences: NotificationPreferences }>("/notifications/preferences");
  return data.preferences;
}

export function useNotificationPreferences() {
  return useQuery({
    queryKey: ["notifications", "preferences"],
    queryFn: fetchPreferences,
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

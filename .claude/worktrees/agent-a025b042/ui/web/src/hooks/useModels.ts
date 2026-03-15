import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/utils/api";

export interface SupportedModelItem {
  model: string;
  provider: "claude" | "gpt" | "gemini" | string;
  label: string;
  description: string;
}

export interface ProviderStatusItem {
  provider: "claude" | "gpt" | "gemini" | string;
  default_model: string;
  configured: boolean;
}

export interface ModelRoleItem {
  config_key: string;
  strategy_code: "A" | "B" | string;
  role: string;
  role_label: string;
  agent_id: string;
  llm_model: string;
  persona: string;
  execution_order: number;
  updated_at: string | null;
}

export interface ModelConfigResponse {
  rule_based_fallback_allowed: boolean;
  supported_models: SupportedModelItem[];
  provider_status: ProviderStatusItem[];
  strategy_a: ModelRoleItem[];
  strategy_b: ModelRoleItem[];
}

export interface ModelRoleUpdateItem {
  config_key: string;
  llm_model: string;
  persona: string;
}

async function fetchModelConfig(): Promise<ModelConfigResponse> {
  const { data } = await api.get<ModelConfigResponse>("/models/config");
  return data;
}

async function updateModelConfig(items: ModelRoleUpdateItem[]): Promise<ModelConfigResponse> {
  const { data } = await api.put<ModelConfigResponse>("/models/config", { items });
  return data;
}

export function useModelConfig() {
  return useQuery({
    queryKey: ["models", "config"],
    queryFn: fetchModelConfig,
    refetchInterval: 30_000,
  });
}

export function useUpdateModelConfig() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (items: ModelRoleUpdateItem[]) => updateModelConfig(items),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["models", "config"] });
    },
  });
}

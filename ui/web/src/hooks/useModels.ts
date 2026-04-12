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
  is_enabled: boolean;
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
  is_enabled: boolean;
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

export interface AddModelRoleRequest {
  strategy_code: "A" | "B";
  role: string;
  llm_model: string;
  persona: string;
}

async function addModelRole(body: AddModelRoleRequest): Promise<ModelConfigResponse> {
  const { data } = await api.post<ModelConfigResponse>("/models/config/roles", body);
  return data;
}

async function deleteModelRole(configKey: string): Promise<ModelConfigResponse> {
  const { data } = await api.delete<ModelConfigResponse>(`/models/config/roles/${configKey}`);
  return data;
}

export function useAddModelRole() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: AddModelRoleRequest) => addModelRole(body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["models", "config"] });
    },
  });
}

export function useDeleteModelRole() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (configKey: string) => deleteModelRole(configKey),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["models", "config"] });
    },
  });
}

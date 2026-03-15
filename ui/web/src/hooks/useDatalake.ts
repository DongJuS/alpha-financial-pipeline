/**
 * ui/src/hooks/useDatalake.ts — 데이터 레이크(S3) 관리 훅
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/utils/api";

export interface DataLakeOverview {
  bucket_name: string;
  total_objects: number;
  total_size_bytes: number;
  total_size_display: string;
  prefixes: Array<{
    prefix: string;
    count: number;
    size: number;
    size_display: string;
  }>;
}

export interface S3ObjectItem {
  key: string;
  size: number;
  size_display: string;
  last_modified: string | null;
  storage_class: string | null;
}

export interface S3ObjectListResponse {
  prefix: string;
  objects: S3ObjectItem[];
  common_prefixes: string[];
  total: number;
}

export interface S3ObjectDetail {
  key: string;
  size: number;
  size_display: string;
  content_type: string | null;
  last_modified: string | null;
  metadata: Record<string, string>;
}

export function useDatalakeOverview() {
  return useQuery({
    queryKey: ["datalake", "overview"],
    queryFn: async (): Promise<DataLakeOverview> => {
      const { data } = await api.get<DataLakeOverview>("/datalake/overview");
      return data;
    },
    staleTime: 60_000,
  });
}

export function useDatalakeObjects(prefix: string) {
  return useQuery({
    queryKey: ["datalake", "objects", prefix],
    queryFn: async (): Promise<S3ObjectListResponse> => {
      const { data } = await api.get<S3ObjectListResponse>("/datalake/objects", {
        params: { prefix },
      });
      return data;
    },
    staleTime: 30_000,
  });
}

export function useDatalakeObjectInfo(key: string | null) {
  return useQuery({
    queryKey: ["datalake", "object-info", key],
    queryFn: async (): Promise<S3ObjectDetail> => {
      const { data } = await api.get<S3ObjectDetail>("/datalake/object-info", {
        params: { key },
      });
      return data;
    },
    enabled: key !== null,
  });
}

export function useDeleteDatalakeObject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (key: string) => {
      const { data } = await api.delete("/datalake/objects", { params: { key } });
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["datalake"] });
    },
  });
}

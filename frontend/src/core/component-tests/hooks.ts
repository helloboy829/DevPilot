import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { useI18n } from "@/core/i18n/hooks";

import {
  createComponent,
  deleteComponent,
  fetchComponentRunReport,
  fetchComponentRuns,
  fetchComponents,
  triggerComponentRun,
  updateComponent,
  type ComponentPayload,
} from "./api";
import type { ComponentTestType } from "./types";

export function useComponents() {
  return useQuery({
    queryKey: ["component-tests"],
    queryFn: fetchComponents,
    refetchInterval: 15000,
    refetchIntervalInBackground: false,
  });
}

export function useComponentRuns(componentId: string | null | undefined) {
  return useQuery({
    queryKey: ["component-tests", "runs", componentId],
    queryFn: () => fetchComponentRuns(componentId ?? ""),
    enabled: Boolean(componentId),
    refetchInterval: 15000,
    refetchIntervalInBackground: false,
  });
}

export function useComponentRunReport(runId: string | null | undefined) {
  return useQuery({
    queryKey: ["component-tests", "report", runId],
    queryFn: () => fetchComponentRunReport(runId ?? ""),
    enabled: Boolean(runId),
  });
}

export function useCreateComponent() {
  const queryClient = useQueryClient();
  const { t } = useI18n();
  return useMutation({
    mutationFn: (payload: ComponentPayload) => createComponent(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["component-tests"] });
    },
    onError: (error: Error) => {
      toast.error(`${t.componentTests.errors.create}: ${error.message}`);
    },
  });
}

export function useUpdateComponent(componentId: string) {
  const queryClient = useQueryClient();
  const { t } = useI18n();
  return useMutation({
    mutationFn: (payload: Partial<ComponentPayload> & { enabled?: boolean }) =>
      updateComponent(componentId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["component-tests"] });
    },
    onError: (error: Error) => {
      toast.error(`${t.componentTests.errors.update}: ${error.message}`);
    },
  });
}

export function useDeleteComponent() {
  const queryClient = useQueryClient();
  const { t } = useI18n();
  return useMutation({
    mutationFn: (componentId: string) => deleteComponent(componentId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["component-tests"] });
    },
    onError: (error: Error) => {
      toast.error(`${t.componentTests.errors.delete}: ${error.message}`);
    },
  });
}

export function useTriggerComponentRun(componentId: string) {
  const queryClient = useQueryClient();
  const { t } = useI18n();
  return useMutation({
    mutationFn: ({
      testType,
      params,
    }: {
      testType: ComponentTestType;
      params: Record<string, unknown>;
    }) => triggerComponentRun(componentId, testType, params),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["component-tests"] });
      void queryClient.invalidateQueries({
        queryKey: ["component-tests", "runs", componentId],
      });
    },
    onError: (error: Error) => {
      toast.error(`${t.componentTests.errors.trigger}: ${error.message}`);
    },
  });
}

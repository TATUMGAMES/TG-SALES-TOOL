import { useMutation, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { ApiError, api } from "./api";
import type { Info, PipelineMeta, PlaybookMeta } from "./api-types";

export function useInfo() {
  return useQuery({ queryKey: ["info"], queryFn: () => api.get<Info>("/system/info"), staleTime: 30_000 });
}

export function usePipelineMeta() {
  return useQuery({ queryKey: ["pipeline-meta"], queryFn: () => api.get<PipelineMeta>("/pipeline/meta"), staleTime: Infinity });
}

export function usePlaybookMeta() {
  return useQuery({ queryKey: ["playbook-meta"], queryFn: () => api.get<PlaybookMeta>("/playbook/meta") });
}

export function showError(error: unknown): void {
  if (error instanceof ApiError) {
    if (error.code === "cancelled") return;
    toast.error(error.message, { description: error.action });
  } else {
    toast.error("Something went wrong.", { description: "Try again." });
  }
}

/** A mutation that shows errors as toasts and refreshes the given queries on success. */
export function useAction<TVars = void, TResult = unknown>(
  fn: (vars: TVars) => Promise<TResult>,
  options: { invalidate?: QueryKey[]; success?: string | ((result: TResult) => string) } = {},
) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: async (result) => {
      await Promise.all((options.invalidate ?? []).map((key) => client.invalidateQueries({ queryKey: key })));
      if (options.success) toast.success(typeof options.success === "function" ? options.success(result) : options.success);
    },
    onError: showError,
  });
}

export function useOnline(): boolean {
  const [online, setOnline] = useState(() => (typeof navigator === "undefined" ? true : navigator.onLine));
  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
    };
  }, []);
  return online;
}

export function useDebounced<T>(value: T, delay = 250): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  }
}

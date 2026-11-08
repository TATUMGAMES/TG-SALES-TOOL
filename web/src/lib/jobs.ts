import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "./api";
import type { JobRef, JobView } from "./api-types";

export type JobState<T> =
  | { status: "idle" }
  | { status: "running"; jobId: string; percent: number; message: string }
  | { status: "succeeded"; result: T }
  | { status: "failed"; error: ApiError }
  | { status: "cancelled"; message: string };

const POLL_MS = 350;

/**
 * Starts a background job on the server and follows its progress.
 * `start` resolves with the result (or rejects with ApiError) when the job ends.
 */
export function useJob<T, A extends unknown[] = []>(starter: (...args: A) => Promise<JobRef>) {
  const [state, setState] = useState<JobState<T>>({ status: "idle" });
  const active = useRef<string | null>(null);
  const mounted = useRef(true);
  const starterRef = useRef(starter);
  starterRef.current = starter;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const start = useCallback(async (...args: A): Promise<T> => {
    setState({ status: "running", jobId: "", percent: 0, message: "Starting…" });
    try {
      const ref = await starterRef.current(...args);
      active.current = ref.job_id;
      for (;;) {
        await new Promise((resolve) => setTimeout(resolve, POLL_MS));
        const job = await api.get<JobView>(`/jobs/${ref.job_id}`);
        if (job.status === "succeeded") {
          if (mounted.current) setState({ status: "succeeded", result: job.result as T });
          return job.result as T;
        }
        if (job.status === "failed") {
          throw new ApiError(job.error?.message ?? "This did not work.", job.error?.action ?? "Try again.", "job", 400);
        }
        if (job.status === "cancelled") {
          if (mounted.current) setState({ status: "cancelled", message: job.message || "Cancelled. Nothing was saved." });
          throw new ApiError("Cancelled.", "Nothing was saved.", "cancelled", 0);
        }
        if (mounted.current) setState({ status: "running", jobId: ref.job_id, percent: job.percent, message: job.message });
      }
    } catch (error) {
      const failure = error instanceof ApiError ? error : new ApiError(String(error), "Try again.", "error", 0);
      if (failure.code !== "cancelled" && mounted.current) setState({ status: "failed", error: failure });
      throw failure;
    } finally {
      active.current = null;
    }
  }, []);

  const cancel = useCallback(async () => {
    if (active.current) await api.post(`/jobs/${active.current}/cancel`);
  }, []);

  const reset = useCallback(() => setState({ status: "idle" }), []);
  return { state, start, cancel, reset, running: state.status === "running" };
}

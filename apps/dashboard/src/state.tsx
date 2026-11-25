import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, ApiError, eventsUrl, withConfirmToken, type CostEstimate, type Job } from "./api";

// ---------------------------------------------------------------- generic data hooks

export function useApi<T>(path: string | null, deps: unknown[] = [], refreshMs = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (!path) return;
    let alive = true;
    const ctrl = new AbortController();
    setLoading(true);
    api
      .get<T>(path, { signal: ctrl.signal })
      .then((d) => {
        if (alive) {
          setData(d);
          setError(null);
        }
      })
      .catch((e) => {
        if (alive && e?.name !== "AbortError") setError(e instanceof ApiError ? e : new ApiError(0, { code: "network", message: String(e?.message ?? e) }));
      })
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
      ctrl.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, tick, ...deps]);

  useEffect(() => {
    if (!refreshMs || !path) return;
    const id = window.setInterval(reload, refreshMs);
    return () => window.clearInterval(id);
  }, [refreshMs, path, reload]);

  return { data, error, loading, reload, setData };
}

// ---------------------------------------------------------------- jobs (SSE + polling fallback)

interface JobsState {
  jobs: Record<string, Job>;
  live: "sse" | "polling" | "connecting";
  upsert: (job: Job) => void;
  refresh: () => Promise<void>;
}

const JobsContext = createContext<JobsState | null>(null);

export function JobsProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<Record<string, Job>>({});
  const [live, setLive] = useState<JobsState["live"]>("connecting");

  const upsert = useCallback((job: Job) => {
    setJobs((prev) => {
      const old = prev[job.id];
      if (old && old.updated_at > job.updated_at && old.status === job.status) return prev;
      return { ...prev, [job.id]: job };
    });
  }, []);

  const refresh = useCallback(async () => {
    try {
      const res = await api.get<{ jobs: Job[] }>("/api/jobs?limit=100");
      setJobs((prev) => {
        const next = { ...prev };
        for (const j of res.jobs) next[j.id] = j;
        return next;
      });
    } catch {
      /* backend offline – the UI shows status elsewhere */
    }
  }, []);

  useEffect(() => {
    void refresh();
    let es: EventSource | null = null;
    let pollId: number | null = null;
    let closed = false;
    const startPolling = () => {
      if (pollId !== null) return;
      setLive("polling");
      pollId = window.setInterval(() => void refresh(), 3000);
    };
    try {
      es = new EventSource(eventsUrl());
      const onJob = (ev: MessageEvent) => {
        try {
          upsert(JSON.parse(ev.data) as Job);
        } catch {
          /* ignore malformed event */
        }
      };
      es.addEventListener("job.created", onJob as EventListener);
      es.addEventListener("job.updated", onJob as EventListener);
      es.addEventListener("job.progress", onJob as EventListener);
      es.onopen = () => {
        if (pollId !== null) {
          window.clearInterval(pollId);
          pollId = null;
        }
        setLive("sse");
        void refresh();
      };
      es.onerror = () => {
        if (!closed) startPolling();
      };
    } catch {
      startPolling();
    }
    return () => {
      closed = true;
      es?.close();
      if (pollId !== null) window.clearInterval(pollId);
    };
  }, [refresh, upsert]);

  const value = useMemo(() => ({ jobs, live, upsert, refresh }), [jobs, live, upsert, refresh]);
  return <JobsContext.Provider value={value}>{children}</JobsContext.Provider>;
}

export function useJobs(filter?: (job: Job) => boolean): Job[] {
  const ctx = useContext(JobsContext);
  if (!ctx) throw new Error("JobsProvider missing");
  return useMemo(() => {
    const list = Object.values(ctx.jobs).filter((j) => (filter ? filter(j) : true));
    return list.sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ctx.jobs]);
}

export function useJobsContext(): JobsState {
  const ctx = useContext(JobsContext);
  if (!ctx) throw new Error("JobsProvider missing");
  return ctx;
}

export function useJob(id: string | null): Job | null {
  const ctx = useJobsContext();
  return id ? ctx.jobs[id] ?? null : null;
}

// ---------------------------------------------------------------- toasts

export interface Toast {
  id: number;
  kind: "info" | "success" | "error";
  text: string;
}

const ToastContext = createContext<{ toasts: Toast[]; push: (kind: Toast["kind"], text: string) => void; dismiss: (id: number) => void } | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const seq = useRef(0);
  const dismiss = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), []);
  const push = useCallback(
    (kind: Toast["kind"], text: string) => {
      const id = ++seq.current;
      setToasts((t) => [...t.slice(-3), { id, kind, text }]);
      window.setTimeout(() => dismiss(id), kind === "error" ? 9000 : 4500);
    },
    [dismiss],
  );
  return <ToastContext.Provider value={{ toasts, push, dismiss }}>{children}</ToastContext.Provider>;
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("ToastProvider missing");
  return ctx;
}

// ---------------------------------------------------------------- cost confirmation

interface PendingCost {
  estimate: CostEstimate;
  message: string;
  resolve: (ok: boolean) => void;
}

const CostContext = createContext<{ pending: PendingCost | null; ask: (estimate: CostEstimate, message: string) => Promise<boolean> } | null>(null);

export function CostProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<PendingCost | null>(null);
  const ask = useCallback(
    (estimate: CostEstimate, message: string) =>
      new Promise<boolean>((resolve) => {
        setPending({
          estimate,
          message,
          resolve: (ok) => {
            setPending(null);
            resolve(ok);
          },
        });
      }),
    [],
  );
  return <CostContext.Provider value={{ pending, ask }}>{children}</CostContext.Provider>;
}

export function useCostPending() {
  const ctx = useContext(CostContext);
  if (!ctx) throw new Error("CostProvider missing");
  return ctx.pending;
}

/**
 * Submit a job-creating POST. A 402 `cost_confirmation_required` response opens the
 * confirmation dialog; on confirm the same request is resent with the confirmation token.
 * Returns the created job (or null if the user declined).
 */
export function useSubmit() {
  const cost = useContext(CostContext);
  const jobs = useContext(JobsContext);
  const toast = useContext(ToastContext);
  if (!cost || !jobs || !toast) throw new Error("providers missing");
  return useCallback(
    async (path: string, body: Record<string, unknown>): Promise<Job | null> => {
      try {
        const res = await api.post<{ job: Job }>(path, body);
        jobs.upsert(res.job);
        return res.job;
      } catch (e) {
        if (e instanceof ApiError && e.status === 402 && e.code === "cost_confirmation_required" && e.estimate?.confirmation_token) {
          const ok = await cost.ask(e.estimate, e.message);
          if (!ok) {
            toast.push("info", "Kostenpflichtige Aktion abgebrochen – nichts wurde ausgeführt.");
            return null;
          }
          const res = await api.post<{ job: Job }>(path, withConfirmToken(path, body, e.estimate.confirmation_token));
          jobs.upsert(res.job);
          return res.job;
        }
        toast.push("error", e instanceof Error ? e.message : String(e));
        return null;
      }
    },
    [cost, jobs, toast],
  );
}

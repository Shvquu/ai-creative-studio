// Typed client for the AI Creative Studio backend (FastAPI, /api/*).

export type JobStatus = "queued" | "running" | "retrying" | "succeeded" | "failed" | "cancelled";

export interface StudioErrorBody {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}

export interface Job {
  id: string;
  type: string;
  status: JobStatus;
  resource: string;
  params: Record<string, unknown>;
  result: Record<string, any> | null;
  error: StudioErrorBody | null;
  progress: number;
  message: string;
  attempts: number;
  max_attempts: number;
  provider: string | null;
  parent_id: string | null;
  retry_of: string | null;
  project: string | null;
  label: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string;
}

export interface QualityIssue {
  check: string;
  severity: "info" | "warning" | "error";
  message: string;
}

export interface Asset {
  id: string;
  path: string;
  kind: "image" | "video" | "audio" | "model3d" | "subtitle" | "document" | "other";
  mime: string | null;
  size_bytes: number | null;
  width: number | null;
  height: number | null;
  duration_s: number | null;
  fps: number | null;
  created_at: string;
  job_id: string | null;
  provider: string | null;
  model: string | null;
  prompt: string | null;
  negative_prompt: string | null;
  seed: number | null;
  params: Record<string, unknown>;
  tags: string[];
  favorite: boolean;
  rating: number | null;
  project: string | null;
  quality: { score: number; passed: boolean; issues?: QualityIssue[]; metrics?: Record<string, unknown> } | null;
  source: string | null;
  notes: string | null;
}

export interface CostEstimate {
  provider: string;
  location: string;
  operation: string;
  model: string | null;
  count: number;
  unit_cost: number;
  total_cost: number;
  currency: string;
  is_free: boolean;
  requires_confirmation: boolean;
  confirmation_token: string | null;
  budget_monthly: number | null;
  budget_spent: number | null;
  budget_remaining: number | null;
  resources: { vram_gb: number | null; ram_gb: number | null; est_seconds: number | null; disk_mb: number | null; note: string };
}

export interface WorkflowInputSpec {
  type: "string" | "text" | "integer" | "number" | "boolean" | "list" | "object" | "asset" | "assets" | "choice" | "color";
  required: boolean;
  default: unknown;
  label: string | null;
  description: string;
  options: unknown[] | null;
  min: number | null;
  max: number | null;
}

export interface WorkflowInfo {
  id: string;
  name: string;
  description: string;
  category: string;
  tags: string[];
  requires: string[];
  fallback: string | null;
  inputs: Record<string, WorkflowInputSpec>;
  steps: { id: string; action: string; label: string; foreach: boolean; conditional: boolean }[];
}

export interface CatalogModel {
  id: string;
  name: string;
  type: "image" | "video" | "upscale";
  family: string;
  description: string;
  files: { name: string; folder: string; url: string; size_gb: number }[];
  size_gb: number;
  min_vram_gb: number;
  rec_vram_gb: number;
  min_ram_gb: number;
  cpu_ok: boolean;
  license: string;
  commercial_use: boolean | "restricted";
  license_note?: string | null;
  tasks: Record<string, string>;
  fits_hardware: boolean;
  hardware_note: string;
  installed: boolean | null;
  missing_files: string[] | null;
}

export interface Capabilities {
  profile: string;
  gpu: boolean;
  accelerator: string;
  ai_image: boolean;
  ai_video: boolean;
  ffmpeg: boolean;
  blender: boolean;
  remotion: boolean;
  rembg: boolean;
}

export interface Presets {
  styles: Record<string, string>;
  camera_moves: Record<string, string>;
  social_formats: Record<string, [number, number]>;
  resolution_presets: Record<string, unknown>;
  aspect_ratios: string[];
  transitions: string[];
}

// ---------------------------------------------------------------- token

const TOKEN_KEY = "acs-api-token";

export function getToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setToken(token: string): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable – token only lives for this session */
  }
}

function withTokenQuery(url: string): string {
  const token = getToken();
  if (!token) return url;
  return `${url}${url.includes("?") ? "&" : "?"}token=${encodeURIComponent(token)}`;
}

export const fileUrl = (id: string, download = false) =>
  withTokenQuery(`/api/assets/${id}/file${download ? "?download=true" : ""}`);
export const thumbUrl = (id: string, size = 384) => withTokenQuery(`/api/assets/${id}/thumbnail?size=${size}`);
export const eventsUrl = () => withTokenQuery("/api/events");

// ---------------------------------------------------------------- errors

export class ApiError extends Error {
  status: number;
  code: string;
  details: Record<string, unknown>;

  constructor(status: number, body: StudioErrorBody) {
    super(body.message);
    this.status = status;
    this.code = body.code;
    this.details = body.details ?? {};
  }

  get estimate(): CostEstimate | null {
    return (this.details.estimate as CostEstimate) ?? null;
  }
}

async function parseError(res: Response): Promise<ApiError> {
  let body: StudioErrorBody = { code: `http_${res.status}`, message: res.statusText || "Fehler" };
  try {
    const data = await res.json();
    if (data?.error?.message) body = data.error;
    else if (data?.detail) {
      // FastAPI validation errors (422)
      const detail = Array.isArray(data.detail)
        ? data.detail.map((d: any) => `${(d.loc ?? []).slice(1).join(".")}: ${d.msg}`).join("; ")
        : String(data.detail);
      body = { code: "validation_error", message: detail };
    }
  } catch {
    /* non-JSON body */
  }
  return new ApiError(res.status, body);
}

// ---------------------------------------------------------------- requests

async function request<T>(method: string, path: string, body?: unknown, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch(path, { method, headers, body: payload, ...init });
  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string, init?: RequestInit) => request<T>("GET", path, undefined, init),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body ?? {}),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body ?? {}),
  upload: <T>(path: string, form: FormData) => request<T>("POST", path, form),
};

/** Insert a cost-confirmation token into a request body (generic /api/jobs puts it into params). */
export function withConfirmToken(path: string, body: Record<string, unknown>, token: string): Record<string, unknown> {
  if (path === "/api/jobs" && body.params && typeof body.params === "object") {
    return { ...body, params: { ...(body.params as Record<string, unknown>), confirm_token: token } };
  }
  return { ...body, confirm_token: token };
}

// ---------------------------------------------------------------- formatting

export function fmtBytes(n: number | null | undefined): string {
  if (n === null || n === undefined) return "–";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

export function fmtSeconds(s: number | null | undefined): string {
  if (s === null || s === undefined) return "–";
  if (s < 60) return `${Math.round(s)} s`;
  if (s < 3600) return `${Math.round(s / 60)} min`;
  return `${(s / 3600).toFixed(1)} h`;
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso);
  return d.toLocaleString("de-DE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export const STATUS_LABEL: Record<JobStatus, string> = {
  queued: "Wartet",
  running: "Läuft",
  retrying: "Wiederholt",
  succeeded: "Fertig",
  failed: "Fehler",
  cancelled: "Abgebrochen",
};

export const isActive = (job: Job) => job.status === "queued" || job.status === "running" || job.status === "retrying";

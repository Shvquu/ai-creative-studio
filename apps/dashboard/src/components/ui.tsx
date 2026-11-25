import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { api, fmtSeconds, fmtTime, isActive, STATUS_LABEL, thumbUrl, type Asset, type CostEstimate, type Job } from "../api";
import { useApi, useCostPending, useToast } from "../state";

// ---------------------------------------------------------------- primitives

export function Card({ title, actions, children, className = "", subtitle }: { title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-head">
          <div>
            {title && <h2 className="card-title">{title}</h2>}
            {subtitle && <p className="card-sub">{subtitle}</p>}
          </div>
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {description && <p className="muted">{description}</p>}
      </div>
      {actions && <div className="row gap-s">{actions}</div>}
    </div>
  );
}

export function Badge({ tone = "neutral", children, title }: { tone?: "neutral" | "ok" | "warn" | "err" | "info" | "accent"; children: ReactNode; title?: string }) {
  return (
    <span className={`badge badge-${tone}`} title={title}>
      {children}
    </span>
  );
}

export function Button({ variant = "secondary", size, children, ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" | "danger"; size?: "s" }) {
  return (
    <button type="button" {...rest} className={`btn btn-${variant} ${size === "s" ? "btn-s" : ""} ${rest.className ?? ""}`}>
      {children}
    </button>
  );
}

export function Field({ label, hint, children, wide }: { label: string; hint?: ReactNode; children: (id: string) => ReactNode; wide?: boolean }) {
  const id = useId();
  return (
    <div className={`field ${wide ? "field-wide" : ""}`}>
      <label htmlFor={id}>{label}</label>
      {children(id)}
      {hint && <small className="muted">{hint}</small>}
    </div>
  );
}

export function Progress({ value, tone }: { value: number; tone?: "ok" | "err" | "warn" }) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return (
    <div className={`progress ${tone ? `progress-${tone}` : ""}`} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
      <div style={{ width: `${pct}%` }} />
    </div>
  );
}

export function Meter({ label, value, max, unit, detail }: { label: string; value: number | null | undefined; max?: number | null; unit?: string; detail?: string }) {
  const pct = value !== null && value !== undefined && max ? value / max : null;
  return (
    <div className="meter">
      <div className="meter-top">
        <span>{label}</span>
        <strong>
          {value === null || value === undefined ? "–" : `${value}${unit ?? ""}`}
          {max ? <span className="muted"> / {max}{unit}</span> : null}
        </strong>
      </div>
      {pct !== null && <Progress value={pct} tone={pct > 0.9 ? "err" : pct > 0.75 ? "warn" : undefined} />}
      {detail && <small className="muted">{detail}</small>}
    </div>
  );
}

export function Spinner({ label = "Lädt …" }: { label?: string }) {
  return (
    <span className="spinner" role="status">
      <span className="spinner-dot" aria-hidden />
      {label}
    </span>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function ErrorNote({ error }: { error: { message: string } | null | undefined }) {
  if (!error) return null;
  return (
    <div className="note note-err" role="alert">
      {error.message}
    </div>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: string }[]; value: T; onChange: (t: T) => void }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.id} type="button" role="tab" aria-selected={value === t.id} className={value === t.id ? "tab active" : "tab"} onClick={() => onChange(t.id)}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- overlays

export function Modal({ title, onClose, children, footer, wide }: { title: string; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    ref.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? "modal-wide" : ""}`} role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} ref={ref}>
        <header className="modal-head">
          <h2>{title}</h2>
          <button type="button" className="icon-btn" aria-label="Schließen" onClick={onClose}>
            ✕
          </button>
        </header>
        <div className="modal-body">{children}</div>
        {footer && <footer className="modal-foot">{footer}</footer>}
      </div>
    </div>
  );
}

export function Drawer({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="overlay overlay-right" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={title}>
        <header className="modal-head">
          <h2>{title}</h2>
          <button type="button" className="icon-btn" aria-label="Schließen" onClick={onClose}>
            ✕
          </button>
        </header>
        <div className="drawer-body">{children}</div>
      </aside>
    </div>
  );
}

export function ToastStack() {
  const { toasts, dismiss } = useToast();
  return (
    <div className="toasts" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast-${t.kind}`} onClick={() => dismiss(t.id)}>
          {t.text}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- cost

export function CostRows({ estimate }: { estimate: CostEstimate }) {
  const r = estimate.resources;
  return (
    <dl className="kv">
      <dt>Provider</dt>
      <dd>
        {estimate.provider} <Badge tone={estimate.location === "cloud" ? "warn" : "ok"}>{estimate.location === "cloud" ? "Cloud" : "lokal"}</Badge>
      </dd>
      <dt>Modell</dt>
      <dd>{estimate.model ?? "automatisch"}</dd>
      <dt>Anzahl</dt>
      <dd>{estimate.count}</dd>
      <dt>Kosten</dt>
      <dd>
        {estimate.is_free ? (
          <Badge tone="ok">kostenlos</Badge>
        ) : (
          <strong>
            {estimate.unit_cost.toFixed(3)} × {estimate.count} = {estimate.total_cost.toFixed(2)} {estimate.currency}
          </strong>
        )}
      </dd>
      {estimate.budget_monthly !== null && (
        <>
          <dt>Budget</dt>
          <dd>
            {estimate.budget_spent?.toFixed(2)} / {estimate.budget_monthly.toFixed(2)} {estimate.currency} verbraucht
          </dd>
        </>
      )}
      <dt>Dauer</dt>
      <dd>{fmtSeconds(r.est_seconds)}</dd>
      <dt>VRAM / RAM</dt>
      <dd>
        {r.vram_gb ? `${r.vram_gb} GB` : "–"} / {r.ram_gb ? `${r.ram_gb} GB` : "–"}
      </dd>
      <dt>Speicher</dt>
      <dd>{r.disk_mb ? `~${r.disk_mb} MB` : "–"}</dd>
      {r.note && (
        <>
          <dt>Hinweis</dt>
          <dd className="muted">{r.note}</dd>
        </>
      )}
    </dl>
  );
}

export function CostDialog() {
  const pending = useCostPending();
  if (!pending) return null;
  return (
    <Modal
      title="Kostenpflichtige Aktion bestätigen"
      onClose={() => pending.resolve(false)}
      footer={
        <>
          <Button variant="ghost" onClick={() => pending.resolve(false)}>
            Abbrechen
          </Button>
          <Button variant="danger" onClick={() => pending.resolve(true)}>
            Kosten akzeptieren und ausführen
          </Button>
        </>
      }
    >
      <div className="note note-warn">{pending.message}</div>
      <CostRows estimate={pending.estimate} />
    </Modal>
  );
}

/** Live estimate (/api/estimate) shown before generating. */
export function EstimatePanel({ type, params }: { type: string; params: Record<string, unknown> }) {
  const [est, setEst] = useState<CostEstimate | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const key = JSON.stringify({ type, params });
  useEffect(() => {
    let alive = true;
    const t = window.setTimeout(() => {
      api
        .post<CostEstimate>("/api/estimate", { type, params })
        .then((e) => alive && (setEst(e), setErr(null)))
        .catch((e) => alive && setErr(e.message));
    }, 350);
    return () => {
      alive = false;
      window.clearTimeout(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return (
    <div className="estimate" aria-live="polite">
      <h3>Schätzung</h3>
      {err && <small className="muted">{err}</small>}
      {est ? <CostRows estimate={est} /> : !err && <Spinner />}
    </div>
  );
}

// ---------------------------------------------------------------- jobs

const statusTone = (s: Job["status"]) => (s === "succeeded" ? "ok" : s === "failed" ? "err" : s === "cancelled" ? "neutral" : s === "retrying" ? "warn" : "info");

export function JobRow({ job, onSelect, compact }: { job: Job; onSelect?: (j: Job) => void; compact?: boolean }) {
  const toast = useToast();
  const cancel = async () => {
    try {
      await api.post(`/api/jobs/${job.id}/cancel`);
      toast.push("info", "Abbruch angefordert");
    } catch (e) {
      toast.push("error", (e as Error).message);
    }
  };
  const retry = async () => {
    try {
      await api.post(`/api/jobs/${job.id}/retry`);
      toast.push("success", "Job erneut gestartet");
    } catch (e) {
      toast.push("error", (e as Error).message);
    }
  };
  return (
    <li className="job">
      <div className="job-main" onClick={() => onSelect?.(job)} role={onSelect ? "button" : undefined} tabIndex={onSelect ? 0 : undefined} onKeyDown={(e) => e.key === "Enter" && onSelect?.(job)}>
        <div className="job-line">
          <Badge tone={statusTone(job.status)}>{STATUS_LABEL[job.status]}</Badge>
          <span className="job-label" title={job.label ?? job.type}>
            {job.label ?? job.type}
          </span>
          {!compact && <span className="muted small">{fmtTime(job.created_at)}</span>}
        </div>
        {isActive(job) && (
          <div className="job-progress">
            <Progress value={job.progress} />
            <small className="muted">
              {Math.round(job.progress * 100)}% · {job.message}
            </small>
          </div>
        )}
        {job.status === "failed" && job.error && <small className="err-text">{job.error.message}</small>}
      </div>
      <div className="job-actions">
        {isActive(job) && (
          <Button size="s" variant="ghost" onClick={cancel} aria-label="Job abbrechen">
            Abbrechen
          </Button>
        )}
        {(job.status === "failed" || job.status === "cancelled") && (
          <Button size="s" variant="ghost" onClick={retry}>
            Wiederholen
          </Button>
        )}
      </div>
    </li>
  );
}

export function JobList({ jobs, empty = "Noch keine Jobs.", onSelect, limit = 20 }: { jobs: Job[]; empty?: string; onSelect?: (j: Job) => void; limit?: number }) {
  if (!jobs.length) return <Empty>{empty}</Empty>;
  return (
    <ul className="jobs">
      {jobs.slice(0, limit).map((j) => (
        <JobRow key={j.id} job={j} onSelect={onSelect} />
      ))}
    </ul>
  );
}

/** Progress + results of a single job (used after submitting). */
export function JobResult({ job, onAssetClick }: { job: Job | null; onAssetClick?: (a: Asset) => void }) {
  if (!job) return null;
  const assets: Asset[] = (job.result?.assets as Asset[]) ?? [];
  return (
    <div className="job-result">
      <JobRow job={job} compact />
      {job.result?.fallback && <div className="note note-warn">Fallback verwendet: {String(job.result.fallback)}</div>}
      {job.result?.fallback_used && (
        <div className="note note-warn">
          Hardware-Fallback: {job.result.fallback_used.from} → {job.result.fallback_used.to} (fehlt: {(job.result.fallback_used.missing ?? []).join(", ")})
        </div>
      )}
      {assets.length > 0 && <AssetGrid assets={assets} onSelect={onAssetClick} small />}
    </div>
  );
}

// ---------------------------------------------------------------- assets

export function AssetThumb({ asset, onClick, selected }: { asset: Asset; onClick?: () => void; selected?: boolean }) {
  const [broken, setBroken] = useState(false);
  const visual = asset.kind === "image" || asset.kind === "video";
  const score = asset.quality?.score;
  return (
    <button type="button" className={`thumb ${selected ? "selected" : ""}`} onClick={onClick} title={asset.prompt ?? asset.path}>
      <div className="thumb-media">
        {visual && !broken ? (
          <img src={thumbUrl(asset.id)} alt={asset.prompt ?? asset.path} loading="lazy" onError={() => setBroken(true)} />
        ) : (
          <span className="thumb-icon" aria-hidden>
            {asset.kind === "audio" ? "♪" : asset.kind === "model3d" ? "◆" : asset.kind === "document" ? "≡" : "□"}
          </span>
        )}
        {asset.kind === "video" && <span className="thumb-tag">▶ {asset.duration_s ? `${asset.duration_s.toFixed(1)} s` : "Video"}</span>}
        {asset.favorite && (
          <span className="thumb-fav" aria-label="Favorit">
            ★
          </span>
        )}
        {score !== undefined && <span className={`thumb-score ${score >= 80 ? "ok" : score >= 60 ? "warn" : "err"}`}>{score}</span>}
      </div>
      <span className="thumb-name">{asset.path.split("/").pop()}</span>
    </button>
  );
}

export function AssetGrid({ assets, onSelect, small, selectedId }: { assets: Asset[]; onSelect?: (a: Asset) => void; small?: boolean; selectedId?: string | null }) {
  if (!assets.length) return <Empty>Keine Assets.</Empty>;
  return (
    <div className={`grid-assets ${small ? "small" : ""}`}>
      {assets.map((a) => (
        <AssetThumb key={a.id} asset={a} onClick={() => onSelect?.(a)} selected={selectedId === a.id} />
      ))}
    </div>
  );
}

export function AssetPicker({ kind = "image", value, onChange, label = "Asset" }: { kind?: string; value: string | null; onChange: (id: string | null) => void; label?: string }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const { data } = useApi<{ assets: Asset[] }>(open ? `/api/assets?kind=${kind}&limit=60${q ? `&q=${encodeURIComponent(q)}` : ""}` : null, [q]);
  const { data: current } = useApi<Asset>(value ? `/api/assets/${value}` : null);
  return (
    <div className="picker">
      <span className="picker-label">{label}</span>
      <div className="row gap-s align-center">
        {value && current ? (
          <div className="picker-current">
            {(current.kind === "image" || current.kind === "video") && <img src={thumbUrl(current.id, 96)} alt="" />}
            <span className="small">{current.path.split("/").pop()}</span>
          </div>
        ) : (
          <span className="muted small">nichts ausgewählt</span>
        )}
        <Button size="s" onClick={() => setOpen(true)}>
          Auswählen …
        </Button>
        {value && (
          <Button size="s" variant="ghost" onClick={() => onChange(null)}>
            Entfernen
          </Button>
        )}
      </div>
      {open && (
        <Modal title={`${label} auswählen`} onClose={() => setOpen(false)} wide>
          <input className="input" placeholder="Suchen …" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Assets durchsuchen" />
          <div className="mt">
            {data ? (
              <AssetGrid
                assets={data.assets}
                small
                selectedId={value}
                onSelect={(a) => {
                  onChange(a.id);
                  setOpen(false);
                }}
              />
            ) : (
              <Spinner />
            )}
          </div>
        </Modal>
      )}
    </div>
  );
}

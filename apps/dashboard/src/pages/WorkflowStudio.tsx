import { useEffect, useMemo, useState } from "react";
import type { Asset, Job, WorkflowInfo, WorkflowInputSpec } from "../api";
import { AssetGrid, AssetPicker, Badge, Button, Card, Drawer, Empty, ErrorNote, Field, JobList, JobRow, PageHeader, Spinner } from "../components/ui";
import { useApi, useJob, useJobs, useSubmit, useToast } from "../state";
import { AssetDetail } from "./AssetLibrary";

const CATEGORY_LABEL: Record<string, string> = {
  images: "Bilder",
  videos: "Videos",
  branding: "Branding",
  "social-media": "Social Media",
  "motion-design": "Motion Design",
};

function kindForInput(name: string): string {
  const n = name.toLowerCase();
  if (n.includes("music") || n.includes("audio")) return "audio";
  if (n.includes("video")) return "video";
  if (n.includes("svg")) return "";
  if (n === "model") return "model3d";
  if (n.includes("image") || n.includes("logo") || n.includes("source")) return "image";
  return "";
}

function initialValue(spec: WorkflowInputSpec): unknown {
  if (spec.default === null || spec.default === undefined) return spec.type === "boolean" ? false : spec.type === "assets" ? [] : "";
  if (spec.type === "list" || spec.type === "object") return Array.isArray(spec.default) && spec.default.every((v) => typeof v !== "object") ? (spec.default as unknown[]).join(", ") : JSON.stringify(spec.default, null, 2);
  return spec.default;
}

function MultiAssetPicker({ value, onChange, kind }: { value: string[]; onChange: (v: string[]) => void; kind: string }) {
  return (
    <div className="stack-s">
      {value.map((id) => (
        <div key={id} className="row gap-s align-center">
          <code className="small">{id.slice(0, 12)}…</code>
          <Button size="s" variant="ghost" onClick={() => onChange(value.filter((v) => v !== id))}>
            Entfernen
          </Button>
        </div>
      ))}
      <AssetPicker kind={kind} value={null} onChange={(id) => id && !value.includes(id) && onChange([...value, id])} label="Asset hinzufügen" />
    </div>
  );
}

function WorkflowForm({ wf, onStarted }: { wf: WorkflowInfo; onStarted: (job: Job) => void }) {
  const submit = useSubmit();
  const toast = useToast();
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [project, setProject] = useState("");
  useEffect(() => {
    setValues(Object.fromEntries(Object.entries(wf.inputs).map(([k, s]) => [k, initialValue(s)])));
  }, [wf]);

  const set = (k: string, v: unknown) => setValues((prev) => ({ ...prev, [k]: v }));

  const run = async (e: React.FormEvent) => {
    e.preventDefault();
    const inputs: Record<string, unknown> = {};
    for (const [k, spec] of Object.entries(wf.inputs)) {
      let v = values[k];
      if (v === "" || v === null || v === undefined || (Array.isArray(v) && !v.length)) continue;
      if (spec.type === "list" || spec.type === "object") {
        const s = String(v).trim();
        if (s.startsWith("[") || s.startsWith("{")) {
          try {
            v = JSON.parse(s);
          } catch {
            toast.push("error", `${spec.label ?? k}: ungültiges JSON`);
            return;
          }
        } else {
          v = s
            .split(/[,\n]/)
            .map((x) => x.trim())
            .filter(Boolean);
        }
      }
      if ((spec.type === "integer" || spec.type === "number") && typeof v === "string") v = Number(v);
      inputs[k] = v;
    }
    const job = await submit(`/api/workflows/${wf.id}/run`, project ? { inputs, project } : { inputs });
    if (job) onStarted(job);
  };

  return (
    <form className="form" onSubmit={run}>
      {Object.entries(wf.inputs).map(([name, spec]) => {
        const human = name.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
        const label = `${spec.label ?? human}${spec.required ? " *" : ""}`;
        const v = values[name];
        if (spec.type === "asset")
          return (
            <div key={name} className="field-wide">
              <AssetPicker kind={kindForInput(name)} value={(v as string) || null} onChange={(id) => set(name, id ?? "")} label={label} />
              {spec.description && <small className="muted">{spec.description}</small>}
            </div>
          );
        if (spec.type === "assets")
          return (
            <div key={name} className="field-wide">
              <span className="picker-label">{label}</span>
              <MultiAssetPicker kind={kindForInput(name)} value={(v as string[]) ?? []} onChange={(ids) => set(name, ids)} />
            </div>
          );
        if (spec.type === "boolean")
          return (
            <label key={name} className="check">
              <input type="checkbox" checked={Boolean(v)} onChange={(e) => set(name, e.target.checked)} /> {label}
            </label>
          );
        const structured = spec.type === "object" || (spec.type === "list" && (spec.description.includes("[") || (Array.isArray(spec.default) && spec.default.some((d) => typeof d === "object"))));
        const wide = spec.type === "text" || structured;
        return (
          <Field key={name} label={label} hint={spec.description || undefined} wide={wide}>
            {(id) => {
              if (spec.type === "choice" && spec.options)
                return (
                  <select id={id} className="input" value={String(v ?? "")} onChange={(e) => set(name, e.target.value)}>
                    {!spec.required && spec.default === null && <option value="">– automatisch –</option>}
                    {spec.options.map((o) => (
                      <option key={String(o)} value={String(o)}>
                        {String(o)}
                      </option>
                    ))}
                  </select>
                );
              if (spec.type === "color") return <input id={id} className="input input-color" type="color" value={String(v || "#000000")} onChange={(e) => set(name, e.target.value.toUpperCase())} />;
              if (spec.type === "integer" || spec.type === "number")
                return <input id={id} className="input" type="number" step={spec.type === "integer" ? 1 : "any"} min={spec.min ?? undefined} max={spec.max ?? undefined} required={spec.required} value={String(v ?? "")} onChange={(e) => set(name, e.target.value)} />;
              if (wide)
                return <textarea id={id} className={`input ${structured ? "mono-if-json" : ""}`} rows={spec.type === "text" ? 3 : 5} required={spec.required} value={String(v ?? "")} onChange={(e) => set(name, e.target.value)} placeholder={structured ? "JSON-Liste, z. B. [{\"prompt\": \"…\", \"duration_s\": 3}]" : undefined} />;
              return <input id={id} className="input" required={spec.required} value={String(v ?? "")} onChange={(e) => set(name, e.target.value)} placeholder={spec.type === "list" ? "Komma-getrennt" : undefined} />;
            }}
          </Field>
        );
      })}
      <Field label="Projekt (optional)">{(id) => <input id={id} className="input" value={project} onChange={(e) => setProject(e.target.value)} />}</Field>
      <div className="form-actions">
        <Button variant="primary" type="submit">
          Workflow starten
        </Button>
      </div>
    </form>
  );
}

function JobDetail({ job, onAsset }: { job: Job; onAsset: (a: Asset) => void }) {
  const r = job.result ?? {};
  return (
    <div className="stack">
      <ul className="jobs">
        <JobRow job={job} />
      </ul>
      {job.error && <ErrorNote error={job.error} />}
      {r.fallback_used && (
        <div className="note note-warn">
          Hardware-Fallback: <strong>{r.fallback_used.from}</strong> → <strong>{r.fallback_used.to}</strong> (fehlt: {(r.fallback_used.missing ?? []).join(", ")})
        </div>
      )}
      {Array.isArray(r.log) && (
        <table className="table">
          <thead>
            <tr>
              <th>Schritt</th>
              <th>Status</th>
              <th>Dauer</th>
              <th>Assets</th>
            </tr>
          </thead>
          <tbody>
            {r.log.map((l: any) => (
              <tr key={l.step}>
                <td>{l.step}</td>
                <td>
                  <Badge tone={l.status === "done" ? "ok" : l.status === "failed" ? "err" : "neutral"}>{l.status === "done" ? "fertig" : l.status === "skipped" ? "übersprungen" : "Fehler"}</Badge>
                  {l.error && <small className="err-text"> {l.error}</small>}
                </td>
                <td>{l.seconds !== undefined ? `${l.seconds} s` : "–"}</td>
                <td>{l.assets ?? "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {r.outputs && (
        <div>
          <h3 className="h3">Ausgaben</h3>
          <pre className="code">{JSON.stringify(r.outputs, null, 2)}</pre>
        </div>
      )}
      {Array.isArray(r.assets) && r.assets.length > 0 && <AssetGrid assets={r.assets as Asset[]} small onSelect={onAsset} />}
    </div>
  );
}

export default function WorkflowStudio() {
  const { data, error } = useApi<WorkflowInfo[]>("/api/workflows");
  const [selected, setSelected] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useJob(jobId);
  const history = useJobs((j: Job) => j.type === "workflow.run");
  const [asset, setAsset] = useState<string | null>(null);
  const caps = useApi<Record<string, unknown>>("/api/system/capabilities");

  const groups = useMemo(() => {
    const g: Record<string, WorkflowInfo[]> = {};
    for (const wf of data ?? []) (g[wf.category] ??= []).push(wf);
    return g;
  }, [data]);
  const wf = data?.find((w) => w.id === selected) ?? null;

  return (
    <div className="page">
      <PageHeader title="Workflow Studio" description="Mehrstufige Produktions-Pipelines mit Fortschritt, Fallbacks und Protokoll." />
      <ErrorNote error={error} />
      {!data && !error && <Spinner />}
      <div className="studio">
        <div className="studio-main">
          {data && !wf && (
            <div className="stack">
              {Object.entries(groups).map(([cat, list]) => (
                <Card key={cat} title={CATEGORY_LABEL[cat] ?? cat}>
                  <div className="wf-grid">
                    {list.map((w) => {
                      const missing = w.requires.filter((r) => caps.data && !caps.data[r]);
                      return (
                        <button key={w.id} type="button" className="wf-card" onClick={() => (setSelected(w.id), setJobId(null))}>
                          <strong>{w.name}</strong>
                          <span className="muted small clamp-3">{w.description}</span>
                          <span className="row gap-xs wrap">
                            {missing.length > 0 && (
                              <Badge tone="warn" title={`fehlt: ${missing.join(", ")}`}>
                                {w.fallback ? "läuft mit Fallback" : "nicht verfügbar"}
                              </Badge>
                            )}
                            <Badge>{w.steps.length} Schritte</Badge>
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </Card>
              ))}
            </div>
          )}
          {wf && (
            <Card
              title={wf.name}
              subtitle={wf.description}
              actions={
                <Button size="s" variant="ghost" onClick={() => setSelected(null)}>
                  ← Alle Workflows
                </Button>
              }
            >
              <div className="row gap-xs wrap mb">
                {wf.steps.map((s, i) => (
                  <span key={s.id} className="step-pill">
                    {i + 1}. {s.label}
                    {s.foreach ? " ↻" : ""}
                    {s.conditional ? " ?" : ""}
                  </span>
                ))}
              </div>
              {wf.requires.length > 0 && (
                <p className="small muted">
                  Benötigt: {wf.requires.join(", ")}
                  {wf.fallback ? ` · Fallback: ${wf.fallback}` : ""}
                </p>
              )}
              <WorkflowForm wf={wf} onStarted={(j) => setJobId(j.id)} />
            </Card>
          )}
          {job && (
            <Card title="Ausführung">
              <JobDetail job={job} onAsset={(a) => setAsset(a.id)} />
            </Card>
          )}
        </div>
        <aside className="studio-side">
          <Card title="Job-Historie" subtitle="Workflow-Läufe">
            {history.length ? <JobList jobs={history} limit={15} onSelect={(j) => setJobId(j.id)} /> : <Empty>Noch keine Workflow-Läufe.</Empty>}
          </Card>
        </aside>
      </div>
      {asset && (
        <Drawer title="Asset" onClose={() => setAsset(null)}>
          <AssetDetail assetId={asset} onChanged={() => undefined} />
        </Drawer>
      )}
    </div>
  );
}

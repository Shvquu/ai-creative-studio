import { useEffect, useState } from "react";
import { api, getToken, setToken, type CatalogModel } from "../api";
import { Badge, Button, Card, ErrorNote, Field, PageHeader, Spinner, Tabs } from "../components/ui";
import { useApi, useToast } from "../state";

type Section = "hardware" | "models" | "providers" | "system" | "costs" | "ui";

interface HardwareResp {
  report: {
    os: string;
    os_version: string;
    architecture: string;
    cpu_model: string;
    cpu_cores_physical: number | null;
    cpu_cores_logical: number | null;
    ram_total_gb: number;
    disk_free_gb: number;
    gpus: { name: string; vendor: string; vram_total_gb: number | null; backend: string; driver_version: string | null }[];
    cuda_version: string | null;
    tools: Record<string, { name: string; available: boolean; version: string | null }>;
    notes: string[];
  };
  decision: { profile: string; reason: string; accelerator: string; effective_vram_gb: number; cpu_only: boolean; warnings: string[] };
  profiles: Record<string, { label: string; criteria: string; notes: string[] }>;
  recommended_models: Record<string, { id: string; name: string; size_gb: number; note: string }[]>;
}

interface ProviderResp {
  name: string;
  display_name: string;
  description: string;
  location: "local" | "cloud";
  cost_model: string;
  requires_api_key: boolean;
  enabled: boolean;
  roles: string[];
  license_note: string | null;
  api_key_present: boolean;
  default_for: string[];
  health: Record<string, { available: boolean; detail: string }>;
}

type SettingsData = Record<string, any>;

function HardwarePanel() {
  const { data, error, reload, loading } = useApi<HardwareResp>("/api/system/hardware");
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Spinner />;
  const r = data.report;
  return (
    <div className="stack">
      <Card
        title={`Aktives Profil: ${data.profiles[data.decision.profile]?.label ?? data.decision.profile}`}
        subtitle={data.decision.reason}
        actions={
          <Button size="s" onClick={() => api.get(`/api/system/hardware?refresh=true`).then(reload)} disabled={loading}>
            Neu erkennen
          </Button>
        }
      >
        <dl className="kv">
          <dt>Betriebssystem</dt>
          <dd>
            {r.os} {r.os_version} ({r.architecture})
          </dd>
          <dt>CPU</dt>
          <dd>
            {r.cpu_model} · {r.cpu_cores_physical ?? "?"} Kerne / {r.cpu_cores_logical ?? "?"} Threads
          </dd>
          <dt>RAM</dt>
          <dd>{r.ram_total_gb} GB</dd>
          <dt>GPU</dt>
          <dd>{r.gpus.length ? r.gpus.map((g) => `${g.name} (${g.vram_total_gb ?? "?"} GB, ${g.backend})`).join(", ") : "keine"}</dd>
          <dt>Beschleuniger</dt>
          <dd>
            {data.decision.accelerator} · effektives VRAM {data.decision.effective_vram_gb} GB {r.cuda_version ? `· CUDA ${r.cuda_version}` : ""}
          </dd>
          <dt>Freier Speicher</dt>
          <dd>{r.disk_free_gb} GB</dd>
        </dl>
        {[...data.decision.warnings, ...r.notes].length > 0 && (
          <ul className="warnings">
            {[...data.decision.warnings, ...r.notes].map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        )}
      </Card>
      <div className="grid-2">
        <Card title="Werkzeuge">
          <table className="table">
            <tbody>
              {Object.values(r.tools).map((t) => (
                <tr key={t.name}>
                  <td>{t.name}</td>
                  <td>
                    <Badge tone={t.available ? "ok" : "warn"}>{t.available ? "vorhanden" : "fehlt"}</Badge>
                  </td>
                  <td className="muted small">{t.version ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
        <Card title="Empfohlene Modelle für dieses Profil">
          {Object.entries(data.recommended_models).map(([task, list]) => (
            <div key={task} className="mb-s">
              <strong className="small">{task}</strong>
              <div className="small">{list.length ? list.map((m) => `${m.name} (${m.size_gb} GB)`).join(" · ") : <span className="muted">– Hardware unzureichend</span>}</div>
            </div>
          ))}
        </Card>
      </div>
      <Card title="Hardwareprofile">
        <div className="grid-3">
          {Object.entries(data.profiles).map(([k, p]) => (
            <div key={k} className={`profile-card ${k === data.decision.profile ? "active" : ""}`}>
              <div className="row space-between">
                <strong>{p.label}</strong>
                {k === data.decision.profile && <Badge tone="accent">aktiv</Badge>}
              </div>
              <small className="muted">{p.criteria}</small>
              <ul className="small">
                {p.notes.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

function ModelsPanel() {
  const { data, error } = useApi<{ catalog: CatalogModel[]; comfyui_error: string | null }>("/api/models");
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Spinner />;
  return (
    <Card title="Modellverwaltung" subtitle="Downloads laufen bewusst nur über die Kommandozeile – mit Größenanzeige und Einzelbestätigung.">
      {data.comfyui_error && <div className="note note-warn">ComfyUI nicht erreichbar – Installationsstatus unbekannt. {data.comfyui_error}</div>}
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Modell</th>
              <th>Typ</th>
              <th>Größe</th>
              <th>Hardware</th>
              <th>Lizenz</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {data.catalog.map((m) => (
              <tr key={m.id}>
                <td>
                  <strong>{m.name}</strong>
                  <div className="muted small">{m.id}</div>
                  {m.installed === false && <code className="cmd">python scripts/models/download_models.py --model {m.id}</code>}
                </td>
                <td>{m.type}</td>
                <td>{m.size_gb} GB</td>
                <td>
                  <Badge tone={m.fits_hardware ? "ok" : "err"} title={m.hardware_note}>
                    {m.fits_hardware ? "passt" : "zu schwach"}
                  </Badge>
                  <div className="muted small">
                    ≥ {m.min_vram_gb} GB VRAM{m.cpu_ok ? " · CPU ok" : ""}
                  </div>
                </td>
                <td>
                  <Badge tone={m.commercial_use === true ? "ok" : m.commercial_use === "restricted" ? "warn" : "err"} title={m.license_note ?? undefined}>
                    {m.commercial_use === true ? "kommerziell ok" : m.commercial_use === "restricted" ? "eingeschränkt" : "nicht kommerziell"}
                  </Badge>
                  <div className="muted small">{m.license}</div>
                </td>
                <td>
                  {m.installed === true && <Badge tone="ok">installiert</Badge>}
                  {m.installed === false && (
                    <Badge tone="warn" title={(m.missing_files ?? []).join(", ")}>
                      fehlt ({(m.missing_files ?? []).length})
                    </Badge>
                  )}
                  {m.installed === null && <Badge>unbekannt</Badge>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function ProvidersPanel() {
  const { data, error, reload } = useApi<ProviderResp[]>("/api/providers");
  const toast = useToast();
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Spinner />;
  const toggle = async (p: ProviderResp) => {
    if (!p.enabled && p.location === "cloud" && !window.confirm(`${p.display_name} ist ein Cloud-Provider und kann Kosten verursachen. Wirklich aktivieren?`)) return;
    try {
      await api.patch(`/api/providers/${p.name}`, { enabled: !p.enabled });
      toast.push("success", `${p.display_name} ${p.enabled ? "deaktiviert" : "aktiviert"}`);
      reload();
    } catch (e) {
      toast.push("error", (e as Error).message);
    }
  };
  return (
    <div className="grid-2">
      {data.map((p) => (
        <Card
          key={p.name}
          title={p.display_name}
          subtitle={p.description}
          actions={
            <label className="switch">
              <input type="checkbox" checked={p.enabled} onChange={() => void toggle(p)} aria-label={`${p.display_name} aktivieren`} />
              <span />
            </label>
          }
        >
          <div className="row gap-s wrap">
            <Badge tone={p.location === "cloud" ? "warn" : "ok"}>{p.location === "cloud" ? "Cloud" : "lokal"}</Badge>
            <Badge tone={p.cost_model === "free" ? "ok" : "warn"}>{p.cost_model === "free" ? "kostenlos" : p.cost_model}</Badge>
            {p.requires_api_key && <Badge tone={p.api_key_present ? "ok" : "err"}>API-Key {p.api_key_present ? "gesetzt" : "fehlt"}</Badge>}
            {p.default_for.map((r) => (
              <Badge key={r} tone="accent">
                Standard: {r}
              </Badge>
            ))}
          </div>
          {p.location === "cloud" && <div className="note note-warn mt-s">Cloud-Provider verursachen Kosten. Jede Aktion muss einzeln bestätigt werden.</div>}
          <ul className="health">
            {Object.entries(p.health).map(([role, h]) => (
              <li key={role}>
                <Badge tone={h.available ? "ok" : "err"}>{role}</Badge> <span className="small">{h.detail}</span>
              </li>
            ))}
          </ul>
          {p.license_note && (
            <small className="muted">
              Lizenz: <a href={p.license_note} target="_blank" rel="noreferrer">{p.license_note}</a>
            </small>
          )}
        </Card>
      ))}
    </div>
  );
}

function SettingsForm({ sections }: { sections: { key: string; title: string; fields: { section: string; key: string; label: string; type?: "number" | "text" | "bool" | "list" | "select"; options?: string[]; hint?: string }[] }[] }) {
  const { data, error, reload } = useApi<{ settings: SettingsData; editable: Record<string, string[]> }>("/api/settings");
  const toast = useToast();
  const [draft, setDraft] = useState<Record<string, Record<string, unknown>>>({});
  useEffect(() => setDraft({}), [data]);
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Spinner />;
  const s = data.settings;
  const value = (section: string, key: string) => (draft[section]?.[key] !== undefined ? draft[section][key] : s[section]?.[key]);
  const set = (section: string, key: string, v: unknown) => setDraft((d) => ({ ...d, [section]: { ...(d[section] ?? {}), [key]: v } }));
  const save = async () => {
    try {
      const r = await api.put<{ restart_required: string[] }>("/api/settings", { updates: draft });
      toast.push("success", r.restart_required.length ? `Gespeichert – Neustart nötig für: ${r.restart_required.join(", ")}` : "Gespeichert");
      reload();
    } catch (e) {
      toast.push("error", (e as Error).message);
    }
  };
  return (
    <div className="stack">
      {sections.map((sec) => (
        <Card key={sec.key} title={sec.title}>
          <div className="form">
            {sec.fields.map((f) => {
              const v = value(f.section, f.key);
              return (
                <Field key={`${f.section}.${f.key}`} label={f.label} hint={f.hint}>
                  {(id) =>
                    f.type === "bool" ? (
                      <label className="check">
                        <input id={id} type="checkbox" checked={Boolean(v)} onChange={(e) => set(f.section, f.key, e.target.checked)} /> aktiv
                      </label>
                    ) : f.type === "select" ? (
                      <select id={id} className="input" value={String(v)} onChange={(e) => set(f.section, f.key, e.target.value)}>
                        {f.options?.map((o) => (
                          <option key={o}>{o}</option>
                        ))}
                      </select>
                    ) : f.type === "list" ? (
                      <input id={id} className="input" value={Array.isArray(v) ? v.join(", ") : String(v ?? "")} onChange={(e) => set(f.section, f.key, e.target.value.split(",").map((x) => x.trim()).filter(Boolean))} />
                    ) : (
                      <input id={id} className="input" type={f.type === "number" ? "number" : "text"} step="any" value={String(v ?? "")} onChange={(e) => set(f.section, f.key, f.type === "number" ? Number(e.target.value) : e.target.value)} />
                    )
                  }
                </Field>
              );
            })}
          </div>
        </Card>
      ))}
      <div className="row gap-s">
        <Button variant="primary" onClick={() => void save()} disabled={!Object.keys(draft).length}>
          Änderungen speichern
        </Button>
        <Button variant="ghost" onClick={() => setDraft({})} disabled={!Object.keys(draft).length}>
          Verwerfen
        </Button>
        <span className="muted small">Gespeichert in configs/studio.local.yaml</span>
      </div>
      <Card title="Speicherorte (nur lesen)">
        <dl className="kv">
          <dt>Projekt</dt>
          <dd className="break">{s.project_root}</dd>
          {Object.entries(s.paths ?? {}).map(([k, v]) => (
            <div key={k} className="kv-row">
              <dt>{k}</dt>
              <dd className="break">{Array.isArray(v) ? v.join(", ") || "–" : String(v)}</dd>
            </div>
          ))}
          <dt>API-Token (Server)</dt>
          <dd>{s.api_token_set ? "gesetzt" : "nicht gesetzt (nur localhost)"}</dd>
        </dl>
      </Card>
    </div>
  );
}

function ComfyTest() {
  const [state, setState] = useState<string | null>(null);
  const test = async () => {
    setState("prüfe …");
    try {
      const s = await api.get<{ comfyui: { available: boolean; detail: string | null; url: string } }>("/api/system/status");
      setState(s.comfyui.available ? `✅ verbunden: ${s.comfyui.detail}` : `❌ nicht erreichbar unter ${s.comfyui.url}`);
    } catch (e) {
      setState(`❌ ${(e as Error).message}`);
    }
  };
  return (
    <div className="row gap-s align-center">
      <Button size="s" onClick={() => void test()}>
        ComfyUI-Verbindung testen
      </Button>
      {state && <span className="small">{state}</span>}
    </div>
  );
}

function UiPanel({ theme, setTheme }: { theme: string; setTheme: (t: "dark" | "light") => void }) {
  const [token, setTokenState] = useState(getToken());
  const toast = useToast();
  return (
    <div className="grid-2">
      <Card title="API-Token" subtitle="Nur nötig, wenn der Server mit ACS_API_TOKEN gestartet wurde. Wird nur in diesem Browser gespeichert.">
        <form
          className="row gap-s"
          onSubmit={(e) => {
            e.preventDefault();
            setToken(token.trim());
            toast.push("success", token.trim() ? "Token gespeichert – Seite neu laden für Live-Updates" : "Token entfernt");
          }}
        >
          <input className="input" type="password" autoComplete="off" value={token} onChange={(e) => setTokenState(e.target.value)} aria-label="API-Token" placeholder="Token" />
          <Button type="submit" variant="primary">
            Speichern
          </Button>
        </form>
      </Card>
      <Card title="Darstellung">
        <div className="segmented" role="group" aria-label="Farbschema">
          <button type="button" className={theme === "dark" ? "active" : ""} onClick={() => setTheme("dark")}>
            Dunkel
          </button>
          <button type="button" className={theme === "light" ? "active" : ""} onClick={() => setTheme("light")}>
            Hell
          </button>
        </div>
      </Card>
    </div>
  );
}

export default function Settings({ theme, setTheme }: { theme: string; setTheme: (t: "dark" | "light") => void }) {
  const [tab, setTab] = useState<Section>("hardware");
  return (
    <div className="page">
      <PageHeader title="Settings" description="Hardware, Modelle, Provider, Verbindungen, Performance und Kostenkontrolle." />
      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "hardware", label: "Hardware" },
          { id: "models", label: "Modelle" },
          { id: "providers", label: "Provider" },
          { id: "system", label: "Verbindungen & Performance" },
          { id: "costs", label: "Kosten" },
          { id: "ui", label: "Oberfläche" },
        ]}
      />
      {tab === "hardware" && <HardwarePanel />}
      {tab === "models" && <ModelsPanel />}
      {tab === "providers" && <ProvidersPanel />}
      {tab === "system" && (
        <>
          <ComfyTest />
          <SettingsForm
            sections={[
              {
                key: "conn",
                title: "Verbindungen & Werkzeuge",
                fields: [
                  { section: "comfyui", key: "url", label: "ComfyUI-URL" },
                  { section: "comfyui", key: "generation_timeout_s", label: "Generierungs-Timeout (s)", type: "number" },
                  { section: "paths", key: "comfyui_dir", label: "ComfyUI-Verzeichnis" },
                  { section: "ffmpeg", key: "ffmpeg_path", label: "FFmpeg-Pfad" },
                  { section: "ffmpeg", key: "ffprobe_path", label: "FFprobe-Pfad" },
                  { section: "ffmpeg", key: "default_crf", label: "Standard-CRF", type: "number", hint: "kleiner = bessere Qualität" },
                  { section: "ffmpeg", key: "preset", label: "x264-Preset", type: "select", options: ["ultrafast", "veryfast", "faster", "fast", "medium", "slow", "slower"] },
                  { section: "blender", key: "blender_path", label: "Blender-Pfad" },
                  { section: "remotion", key: "npx_path", label: "npx-Pfad (Remotion)" },
                  { section: "paths", key: "extra_allowed_dirs", label: "Zusätzlich erlaubte Ordner", type: "list", hint: "Komma-getrennt" },
                ],
              },
              {
                key: "perf",
                title: "Performance & Qualität",
                fields: [
                  { section: "hardware", key: "profile", label: "Hardwareprofil", type: "select", options: ["auto", "low", "mid", "high"] },
                  { section: "jobs", key: "gpu_concurrency", label: "Parallele GPU-Jobs", type: "number" },
                  { section: "jobs", key: "cpu_concurrency", label: "Parallele CPU-Jobs", type: "number" },
                  { section: "jobs", key: "workflow_concurrency", label: "Parallele Workflows", type: "number" },
                  { section: "jobs", key: "max_attempts", label: "Max. Versuche pro Job", type: "number" },
                  { section: "quality", key: "auto_check", label: "Automatische Qualitätsprüfung", type: "bool" },
                  { section: "quality", key: "min_sharpness", label: "Min. Schärfe", type: "number" },
                  { section: "quality", key: "min_score", label: "Min. Qualitäts-Score", type: "number" },
                ],
              },
            ]}
          />
        </>
      )}
      {tab === "costs" && (
        <>
          <div className="note">
            Standardmäßig arbeitet das Studio vollständig lokal und kostenlos. Cloud-Provider sind deaktiviert. Ein Monatsbudget von 0 blockiert jede kostenpflichtige Aktion; jede Aktion muss
            zusätzlich einzeln bestätigt werden.
          </div>
          <SettingsForm
            sections={[
              {
                key: "costs",
                title: "Kostenkontrolle",
                fields: [
                  { section: "costs", key: "monthly_budget", label: "Monatsbudget", type: "number", hint: "0 = keine kostenpflichtigen Aktionen" },
                  { section: "costs", key: "max_cost_per_job", label: "Max. Kosten pro Job", type: "number" },
                ],
              },
            ]}
          />
        </>
      )}
      {tab === "ui" && <UiPanel theme={theme} setTheme={setTheme} />}
    </div>
  );
}

import type { Asset, Job } from "../api";
import { AssetGrid, Badge, Card, Empty, ErrorNote, JobList, Meter, PageHeader, Spinner } from "../components/ui";
import { useApi, useJobs } from "../state";

interface ProviderHealth {
  available: boolean;
  detail: string;
  version: string | null;
}

interface Status {
  profile: { profile: string; reason: string; accelerator: string; effective_vram_gb: number; cpu_only: boolean; warnings: string[] };
  hardware: { os: string; cpu: string; cores: number; ram_total_gb: number; cuda: string | null; gpus: { name: string; vram_total_gb: number | null }[] };
  usage: { cpu_pct: number; ram_used_gb: number; ram_total_gb: number; ram_pct: number; gpus: { name: string; vram_total_gb: number | null; vram_free_gb: number | null; utilization_pct?: number | null }[] };
  disk: { free_gb: number; total_gb: number };
  comfyui: { available: boolean; detail: string | null; url: string };
  providers: Record<string, Record<string, ProviderHealth>>;
  jobs: Record<string, number>;
  assets: { total: number; total_bytes: number; favorites: number; by_kind: Record<string, { count: number; bytes: number }> };
}

const PROFILE_LABEL: Record<string, string> = { low: "Low-End", mid: "Mid-Range", high: "High-End" };

export default function Dashboard({ navigate }: { navigate: (route: string) => void }) {
  const { data, error } = useApi<Status>("/api/system/status", [], 5000);
  const recent = useApi<{ assets: Asset[] }>("/api/assets?limit=8", [], 5000);
  const active = useJobs((j: Job) => j.status === "queued" || j.status === "running" || j.status === "retrying");
  const recentJobs = useJobs();

  return (
    <div className="page">
      <PageHeader title="Dashboard" description="Systemstatus, laufende Generierungen und die neuesten Ergebnisse." />
      <ErrorNote error={error} />
      {!data && !error && <Spinner />}
      {data && (
        <>
          <div className="grid-stats">
            <div className="stat">
              <span className="stat-label">Hardwareprofil</span>
              <span className="stat-value">{PROFILE_LABEL[data.profile.profile] ?? data.profile.profile}</span>
              <span className="muted small">{data.profile.reason}</span>
            </div>
            <div className="stat">
              <span className="stat-label">ComfyUI</span>
              <span className="stat-value">
                <Badge tone={data.comfyui.available ? "ok" : "err"}>{data.comfyui.available ? "verbunden" : "offline"}</Badge>
              </span>
              <span className="muted small">{data.comfyui.detail ?? data.comfyui.url}</span>
            </div>
            <div className="stat">
              <span className="stat-label">Aktive Jobs</span>
              <span className="stat-value">{(data.jobs.running ?? 0) + (data.jobs.queued ?? 0) + (data.jobs.retrying ?? 0)}</span>
              <span className="muted small">
                {data.jobs.succeeded ?? 0} fertig · {data.jobs.failed ?? 0} Fehler
              </span>
            </div>
            <div className="stat">
              <span className="stat-label">Assets</span>
              <span className="stat-value">{data.assets.total}</span>
              <span className="muted small">{data.assets.favorites} Favoriten</span>
            </div>
          </div>

          <div className="grid-2">
            <Card title="Ressourcen" subtitle={`${data.hardware.cpu} · ${data.hardware.os}`}>
              <div className="stack">
                <Meter label="CPU" value={Math.round(data.usage.cpu_pct)} max={100} unit="%" detail={`${data.hardware.cores} Threads`} />
                <Meter label="RAM" value={data.usage.ram_used_gb} max={data.usage.ram_total_gb} unit=" GB" />
                {data.usage.gpus.length ? (
                  data.usage.gpus.map((g, i) => (
                    <Meter
                      key={i}
                      label={`VRAM · ${g.name}`}
                      value={g.vram_total_gb !== null && g.vram_free_gb !== null ? Math.round((g.vram_total_gb - g.vram_free_gb) * 10) / 10 : null}
                      max={g.vram_total_gb}
                      unit=" GB"
                      detail={g.utilization_pct !== undefined && g.utilization_pct !== null ? `GPU-Auslastung ${g.utilization_pct}%` : undefined}
                    />
                  ))
                ) : (
                  <div className="note">Keine GPU erkannt – CPU-Modus (Videogenerierung nicht verfügbar).</div>
                )}
                <Meter label="Speicher belegt" value={Math.round((data.disk.total_gb - data.disk.free_gb) * 10) / 10} max={data.disk.total_gb} unit=" GB" detail={`${data.disk.free_gb} GB frei`} />
              </div>
              {data.profile.warnings.length > 0 && (
                <ul className="warnings">
                  {data.profile.warnings.map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              )}
            </Card>

            <Card title="Provider" subtitle="Lokale Engines und ihr Zustand">
              <div className="provider-grid">
                {Object.entries(data.providers).flatMap(([name, roles]) =>
                  Object.entries(roles).map(([role, h]) => (
                    <div key={`${name}/${role}`} className="provider-cell">
                      <div className="row space-between align-center">
                        <strong>{name}</strong>
                        <Badge tone={h.available ? "ok" : "err"}>{h.available ? "bereit" : "nicht verfügbar"}</Badge>
                      </div>
                      <span className="muted small">{role}</span>
                      <span className="small clamp-2" title={h.detail}>
                        {h.detail}
                      </span>
                    </div>
                  )),
                )}
              </div>
            </Card>
          </div>

          <div className="grid-2">
            <Card title="Aktive Generierungen" actions={<a href="#/workflows">Alle Jobs →</a>}>
              <JobList jobs={active} empty="Gerade läuft nichts." />
            </Card>
            <Card title="Letzte Jobs">
              <JobList jobs={recentJobs} limit={6} />
            </Card>
          </div>

          <Card title="Neueste Ergebnisse" actions={<button type="button" className="link-btn" onClick={() => navigate("assets")}>Zur Bibliothek →</button>}>
            {recent.data ? recent.data.assets.length ? <AssetGrid assets={recent.data.assets} small onSelect={() => navigate("assets")} /> : <Empty>Noch keine Assets – starte im Image Studio.</Empty> : <Spinner />}
          </Card>
        </>
      )}
    </div>
  );
}

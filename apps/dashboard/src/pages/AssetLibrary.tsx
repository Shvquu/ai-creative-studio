import { useRef, useState } from "react";
import { api, fileUrl, fmtBytes, fmtTime, type Asset } from "../api";
import { AssetGrid, Badge, Button, Card, Drawer, Empty, ErrorNote, Field, Modal, PageHeader, Spinner } from "../components/ui";
import { useApi, useToast } from "../state";

interface Stats {
  total: number;
  favorites: number;
  by_kind: Record<string, { count: number; bytes: number }>;
  tags: { tag: string; count: number }[];
  projects: string[];
}

const KINDS: [string, string][] = [
  ["", "Alle"],
  ["image", "Bilder"],
  ["video", "Videos"],
  ["audio", "Audio"],
  ["model3d", "3D"],
  ["document", "Dokumente"],
];

export function AssetDetail({ assetId, onChanged }: { assetId: string; onChanged: () => void }) {
  const { data, error, reload } = useApi<Asset & { sidecar: Record<string, unknown> | null; exists: boolean }>(`/api/assets/${assetId}`);
  const toast = useToast();
  const [tagText, setTagText] = useState("");
  const [showSidecar, setShowSidecar] = useState(false);
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Spinner />;
  const a = data;
  const patch = async (body: Record<string, unknown>) => {
    try {
      await api.patch(`/api/assets/${a.id}`, body);
      reload();
      onChanged();
    } catch (e) {
      toast.push("error", (e as Error).message);
    }
  };
  return (
    <div className="stack">
      <div className="preview">
        {a.kind === "image" && <img src={fileUrl(a.id)} alt={a.prompt ?? a.path} />}
        {a.kind === "video" && <video src={fileUrl(a.id)} controls preload="metadata" />}
        {a.kind === "audio" && <audio src={fileUrl(a.id)} controls />}
        {!["image", "video", "audio"].includes(a.kind) && <Empty>Keine Vorschau für {a.kind}</Empty>}
      </div>
      <div className="row gap-s wrap">
        <Button variant={a.favorite ? "primary" : "secondary"} onClick={() => patch({ favorite: !a.favorite })} aria-pressed={a.favorite}>
          {a.favorite ? "★ Favorit" : "☆ Favorisieren"}
        </Button>
        <a className="btn btn-secondary" href={fileUrl(a.id, true)} download>
          Herunterladen
        </a>
        {a.kind === "document" && (
          <a className="btn btn-ghost" href={fileUrl(a.id)} target="_blank" rel="noreferrer">
            Öffnen
          </a>
        )}
      </div>
      <dl className="kv">
        <dt>Datei</dt>
        <dd className="break">{a.path}</dd>
        <dt>Typ</dt>
        <dd>
          {a.kind} · {a.mime}
        </dd>
        <dt>Größe</dt>
        <dd>
          {fmtBytes(a.size_bytes)}
          {a.width ? ` · ${a.width}×${a.height}` : ""}
          {a.duration_s ? ` · ${a.duration_s.toFixed(2)} s` : ""}
          {a.fps ? ` · ${a.fps} fps` : ""}
        </dd>
        <dt>Erstellt</dt>
        <dd>{fmtTime(a.created_at)}</dd>
        {a.provider && (
          <>
            <dt>Provider / Modell</dt>
            <dd>
              {a.provider} {a.model ? `· ${a.model}` : ""}
            </dd>
          </>
        )}
        {a.seed !== null && (
          <>
            <dt>Seed</dt>
            <dd>{a.seed}</dd>
          </>
        )}
        {a.prompt && (
          <>
            <dt>Prompt</dt>
            <dd className="break">{a.prompt}</dd>
          </>
        )}
        {a.negative_prompt && (
          <>
            <dt>Negativ</dt>
            <dd className="break muted">{a.negative_prompt}</dd>
          </>
        )}
        {a.project && (
          <>
            <dt>Projekt</dt>
            <dd>{a.project}</dd>
          </>
        )}
        {a.quality && (
          <>
            <dt>Qualität</dt>
            <dd>
              <Badge tone={a.quality.passed ? "ok" : "err"}>{a.quality.score}/100</Badge>
              {a.quality.issues?.length ? (
                <ul className="issues">
                  {a.quality.issues.map((i, k) => (
                    <li key={k} className={`sev-${i.severity}`}>
                      {i.message}
                    </li>
                  ))}
                </ul>
              ) : (
                <span className="muted small"> keine Befunde</span>
              )}
            </dd>
          </>
        )}
      </dl>
      <div>
        <span className="picker-label">Tags</span>
        <div className="row gap-s wrap">
          {a.tags.map((t) => (
            <span key={t} className="chip">
              {t}
              <button type="button" aria-label={`Tag ${t} entfernen`} onClick={() => patch({ remove_tags: [t] })}>
                ×
              </button>
            </span>
          ))}
        </div>
        <form
          className="row gap-s mt-s"
          onSubmit={(e) => {
            e.preventDefault();
            if (tagText.trim()) void patch({ add_tags: tagText.split(",").map((s) => s.trim()) });
            setTagText("");
          }}
        >
          <input className="input" value={tagText} onChange={(e) => setTagText(e.target.value)} placeholder="Tag hinzufügen (Komma-getrennt)" aria-label="Tags hinzufügen" />
          <Button type="submit" size="s">
            Hinzufügen
          </Button>
        </form>
      </div>
      {data.sidecar && (
        <div>
          <Button size="s" variant="ghost" onClick={() => setShowSidecar((s) => !s)} aria-expanded={showSidecar}>
            {showSidecar ? "Metadaten ausblenden" : "Sidecar-Metadaten (Reproduzierbarkeit) anzeigen"}
          </Button>
          {showSidecar && <pre className="code">{JSON.stringify(data.sidecar, null, 2)}</pre>}
        </div>
      )}
    </div>
  );
}

export default function AssetLibrary() {
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("");
  const [tag, setTag] = useState("");
  const [project, setProject] = useState("");
  const [favorite, setFavorite] = useState(false);
  const [sort, setSort] = useState("newest");
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [organizePlan, setOrganizePlan] = useState<{ rule: string; moves: { from: string; to: string }[]; count: number } | null>(null);
  const [rule, setRule] = useState("by_kind");
  const fileInput = useRef<HTMLInputElement>(null);
  const toast = useToast();
  const limit = 48;
  const params = new URLSearchParams({ limit: String(limit), offset: String(page * limit), sort });
  if (q) params.set("q", q);
  if (kind) params.set("kind", kind);
  if (tag) params.set("tags", tag);
  if (project) params.set("project", project);
  if (favorite) params.set("favorite", "true");
  const { data, error, reload } = useApi<{ assets: Asset[]; total: number }>(`/api/assets?${params.toString()}`);
  const stats = useApi<Stats>("/api/assets/meta/stats");

  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    for (const f of Array.from(files)) {
      const form = new FormData();
      form.append("file", f);
      try {
        await api.upload("/api/assets/upload", form);
        toast.push("success", `Hochgeladen: ${f.name}`);
      } catch (e) {
        toast.push("error", `${f.name}: ${(e as Error).message}`);
      }
    }
    reload();
    stats.reload();
  };

  const rescan = async () => {
    const r = await api.post<{ added: string[]; removed: string[] }>("/api/assets/rescan");
    toast.push("success", `Neu indiziert: ${r.added.length}, entfernt: ${r.removed.length}`);
    reload();
    stats.reload();
  };

  const planOrganize = async () => {
    try {
      setOrganizePlan(await api.post("/api/assets/organize", { rule, dry_run: true }));
    } catch (e) {
      toast.push("error", (e as Error).message);
    }
  };

  const applyOrganize = async () => {
    const r = await api.post<{ count: number }>("/api/assets/organize", { rule, dry_run: false });
    toast.push("success", `${r.count} Dateien verschoben`);
    setOrganizePlan(null);
    reload();
  };

  const totalPages = data ? Math.max(1, Math.ceil(data.total / limit)) : 1;

  return (
    <div className="page">
      <PageHeader
        title="Asset Library"
        description="Alle generierten und hochgeladenen Medien mit Metadaten, Tags und Qualitätsbewertung."
        actions={
          <>
            <input ref={fileInput} type="file" multiple hidden onChange={(e) => void upload(e.target.files)} aria-hidden />
            <Button variant="primary" onClick={() => fileInput.current?.click()}>
              Hochladen
            </Button>
            <Button onClick={() => void rescan()}>Neu einlesen</Button>
            <Button onClick={() => void planOrganize()}>Organisieren …</Button>
          </>
        }
      />
      <Card>
        <div className="filters">
          <input className="input" type="search" placeholder="Suche in Prompt, Dateiname, Tags …" value={q} onChange={(e) => (setQ(e.target.value), setPage(0))} aria-label="Suche" />
          <div className="segmented" role="group" aria-label="Typ">
            {KINDS.map(([k, label]) => (
              <button key={k} type="button" className={kind === k ? "active" : ""} onClick={() => (setKind(k), setPage(0))}>
                {label}
                {k && stats.data?.by_kind[k] ? <span className="count">{stats.data.by_kind[k].count}</span> : null}
              </button>
            ))}
          </div>
          <select className="input" value={tag} onChange={(e) => (setTag(e.target.value), setPage(0))} aria-label="Tag-Filter">
            <option value="">Alle Tags</option>
            {stats.data?.tags.map((t) => (
              <option key={t.tag} value={t.tag}>
                {t.tag} ({t.count})
              </option>
            ))}
          </select>
          <select className="input" value={project} onChange={(e) => (setProject(e.target.value), setPage(0))} aria-label="Projekt-Filter">
            <option value="">Alle Projekte</option>
            {stats.data?.projects.map((p) => (
              <option key={p}>{p}</option>
            ))}
          </select>
          <select className="input" value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sortierung">
            <option value="newest">Neueste zuerst</option>
            <option value="oldest">Älteste zuerst</option>
            <option value="name">Name</option>
            <option value="size">Größe</option>
            <option value="rating">Bewertung</option>
          </select>
          <label className="check">
            <input type="checkbox" checked={favorite} onChange={(e) => (setFavorite(e.target.checked), setPage(0))} /> nur Favoriten
          </label>
        </div>
      </Card>
      <ErrorNote error={error} />
      {!data ? (
        <Spinner />
      ) : (
        <>
          <p className="muted small">{data.total} Assets</p>
          <AssetGrid assets={data.assets} onSelect={(a) => setSelected(a.id)} />
          {totalPages > 1 && (
            <div className="row gap-s align-center center mt">
              <Button size="s" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
                ← Zurück
              </Button>
              <span className="small">
                Seite {page + 1} / {totalPages}
              </span>
              <Button size="s" disabled={page + 1 >= totalPages} onClick={() => setPage((p) => p + 1)}>
                Weiter →
              </Button>
            </div>
          )}
        </>
      )}
      {selected && (
        <Drawer title="Asset-Details" onClose={() => setSelected(null)}>
          <AssetDetail assetId={selected} onChanged={() => (reload(), stats.reload())} />
        </Drawer>
      )}
      {organizePlan && (
        <Modal
          title="Assets organisieren"
          onClose={() => setOrganizePlan(null)}
          wide
          footer={
            <>
              <Button variant="ghost" onClick={() => setOrganizePlan(null)}>
                Abbrechen
              </Button>
              <Button variant="primary" disabled={!organizePlan.count} onClick={() => void applyOrganize()}>
                {organizePlan.count} Dateien verschieben
              </Button>
            </>
          }
        >
          <Field label="Regel">
            {(id) => (
              <select id={id} className="input" value={rule} onChange={(e) => setRule(e.target.value)}>
                <option value="by_kind">nach Typ (images/, videos/ …)</option>
                <option value="by_project">nach Projekt</option>
                <option value="by_date">nach Monat</option>
              </select>
            )}
          </Field>
          <div className="row gap-s mt-s">
            <Button size="s" onClick={() => void planOrganize()}>
              Vorschau aktualisieren
            </Button>
          </div>
          <p className="muted small">Vorschau (Dry-Run) – es wird erst nach Bestätigung etwas verschoben.</p>
          {organizePlan.moves.length ? (
            <ul className="moves">
              {organizePlan.moves.slice(0, 100).map((m) => (
                <li key={m.from}>
                  <code>{m.from}</code> → <code>{m.to}</code>
                </li>
              ))}
            </ul>
          ) : (
            <Empty>Alles ist bereits organisiert.</Empty>
          )}
        </Modal>
      )}
    </div>
  );
}
